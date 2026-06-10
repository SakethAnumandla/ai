"""Phase 3 copilot pre-LLM pipeline — references, slots, continuity, context enrichment."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.conversation.state_machine import ConversationStateMachine
from app.ai.memory.context_scope import ContextScopeFilter
from app.ai.memory.decay_service import MemoryDecayService
from app.ai.memory.audit import MemoryAuditService
from app.ai.memory.policy import MemoryPolicyService
from app.ai.memory.repository import AIRepository
from app.ai.memory.explanations import MemoryExplanationBuilder
from app.ai.preferences.service import UserPreferenceService
from app.ai.graph.workflow_graph import WorkflowEntityGraph
from app.ai.resolution.reference_resolver import ReferenceResolver
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.schemas.workflow import ResolvedReferences, WorkflowScope
from app.ai.services.memory_service import MemoryService
from app.ai.workflow.continuity import WorkflowContinuityService
from app.ai.workflow.recovery import WorkflowRecoveryService
from app.ai.workflow.snapshot import WorkflowSnapshotService
from app.ai.confirmation.service import ConfirmationService
from app.ai.draft_confirm import draft_confirm_tool_arguments, is_draft_confirmation
from app.ai.orchestrator.intent import IntentDetector, UserIntent
from app.models import User


@dataclass
class CopilotPreflightResult:
    intercept_message: Optional[str] = None
    execute_tool: Optional[str] = None
    execute_arguments: Optional[Dict[str, Any]] = None
    resolved: Optional[ResolvedReferences] = None
    scope: WorkflowScope = WorkflowScope.GENERAL
    preference_lines: List[str] = field(default_factory=list)
    workflow_lines: List[str] = field(default_factory=list)
    graph_lines: List[str] = field(default_factory=list)
    reference_context: Optional[str] = None
    pending_intent_summary: Optional[str] = None
    memory_explanations: List[str] = field(default_factory=list)


class CopilotPreflight:
    """Runs decay, recovery, continuity, slot filling, and context enrichment before the LLM."""

    def __init__(
        self,
        db: Session,
        memory: MemoryService,
        repository: AIRepository,
        confirmation: ConfirmationService,
    ):
        self._db = db
        self._memory = memory
        self._resolver = ReferenceResolver(db)
        self._state_machine = ConversationStateMachine()
        self._continuity = WorkflowContinuityService(db, memory)
        self._recovery = WorkflowRecoveryService(db, memory, confirmation)
        policy = MemoryPolicyService(db)
        audit = MemoryAuditService(db)
        self._preferences = UserPreferenceService(db, repository, policy=policy, audit=audit)
        self._graph = WorkflowEntityGraph(repository, policy)
        self._scope_filter = ContextScopeFilter()
        self._snapshot = WorkflowSnapshotService(db, confirmation)
        self._decay = MemoryDecayService(repository, memory, policy=policy, audit=audit)
        self._intent = IntentDetector()
        self._explanation_builder = MemoryExplanationBuilder()

    async def run(
        self,
        ctx: SessionContext,
        user: User,
        user_content: str,
        *,
        skip_slot_machine: bool = False,
    ) -> CopilotPreflightResult:
        await self._decay.run_session_hygiene(ctx)
        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        intent = self._intent.detect(user_content)
        out = CopilotPreflightResult()

        draft = await self._memory.get_draft_expense(ctx)
        if draft and draft.expense_id and (
            intent.intent == UserIntent.CONFIRM or is_draft_confirmation(user_content)
        ):
            out.execute_tool = "expense.create.v1"
            out.execute_arguments = draft_confirm_tool_arguments(draft)
            return out

        explicit_continue = (
            intent.intent == UserIntent.CONTINUE_WORKFLOW
            or self._continuity.is_continue_intent(user_content)
        )

        recovery = await self._recovery.assess(
            ctx,
            user_text=user_content,
            explicit_continue=explicit_continue,
            intent=intent,
        )
        if (
            recovery.safe_prompt
            and recovery.block_blind_resume
            and not explicit_continue
        ):
            out.intercept_message = recovery.safe_prompt
            out.workflow_lines.append(recovery.safe_prompt)
            return out

        continuity = await self._continuity.try_resume(
            ctx, user_content, recovery=recovery
        )
        if continuity.handled and continuity.message and not continuity.resumed_state:
            out.intercept_message = continuity.message
            return out

        resolved = self._resolver.resolve(user.id, user_content)
        out.resolved = resolved
        prefill = resolved.apply_to_slots({})

        active_state = await self._memory.get_workflow_state(ctx)
        if continuity.resumed_state:
            active_state = continuity.resumed_state

        if not skip_slot_machine:
            sm_result = self._state_machine.process_turn(
                user_content,
                active_state,
                session_id=ctx.session_id,
                prefill=prefill,
            )
            if sm_result.handled:
                if sm_result.assistant_message and not sm_result.ready_tool_name:
                    msg = sm_result.assistant_message
                    if (
                        resolved.vendor_name
                        and sm_result.updated_state
                        and resolved.source_expense_id
                        and "same" in " ".join(resolved.matched_phrases).lower()
                    ):
                        msg = f"Using {resolved.vendor_name} from your previous expense. {msg}"
                    if (
                        sm_result.updated_state
                        and sm_result.updated_state.pending_slots
                        and sm_result.updated_state.pending_slots[0] == "payment_method"
                    ):
                        suggestion = self._preferences.suggest_payment(
                            tu,
                            category=sm_result.updated_state.slots.get("main_category"),
                        )
                        if suggestion:
                            msg = self._explanation_builder.append_to_prompt(
                                suggestion.prompt, suggestion.explanation
                            )
                            if suggestion.explanation:
                                out.memory_explanations.append(
                                    suggestion.explanation.format_user_facing()
                                )
                    out.intercept_message = msg
                    if sm_result.updated_state:
                        sm_result.updated_state.session_id = ctx.session_id
                        await self._memory.set_workflow_state(ctx, sm_result.updated_state)
                        await self._memory.set_draft_expense(
                            ctx, self._state_machine.state_to_draft(sm_result.updated_state)
                        )
                    return out

                if sm_result.ready_tool_name:
                    out.execute_tool = sm_result.ready_tool_name
                    out.execute_arguments = sm_result.ready_arguments
                    if sm_result.clear_state:
                        await self._memory.clear_workflow_state(ctx)
                    return out

        scope = self._scope_filter.detect_scope(
            user_content,
            intent=intent.intent,
            active_scope=active_state.scope if active_state else None,
        )
        out.scope = scope

        prefs = self._preferences.get_preferences_summary(tu)
        out.preference_lines = self._scope_filter.filter_memory_lines(prefs, scope)

        snap = self._snapshot.build(ctx, scope=scope)
        out.workflow_lines = self._scope_filter.filter_memory_lines(snap.summary_lines, scope)

        out.graph_lines = self._scope_filter.filter_memory_lines(
            self._graph.context_lines(tu), scope
        )

        if resolved.notes:
            out.reference_context = " ".join(resolved.notes)

        pending = await self._memory.get_pending_intent(ctx)
        if pending:
            out.pending_intent_summary = f"{pending.intent_type}: {pending.parameters}"

        return out
