"""
Phase 2/3 AIOrchestrator — ranked memory, partitioned context, argument repair, post-processing, DLQ.
"""
import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional, Union

from sqlalchemy.orm import Session

from app.ai.classifier.response_classifier import ResponseClassifier, ResponseClassification
from app.ai.confirmation.affirm import is_affirmation, is_denial
from app.ai.draft_confirm import draft_confirm_tool_arguments, is_draft_confirmation
from app.ai.vendor_guard import looks_like_chat_command, resolve_vendor_from_draft, sanitize_vendor_name
from app.ai.confirmation.service import ConfirmationService
from app.ai.dead_letter.service import DeadLetterQueueService
from app.ai.idempotency.service import IdempotencyService
from app.ai.memory.context_builder import ContextBuilder, replace_last_user_message_content
from app.ai.observability import get_or_create_trace_context, get_trace_context
from app.ai.orchestrator.intent import ConversationIntentType, IntentDetector, UserIntent
from app.ai.permissions.matrix import ToolPermissionMatrix
from app.ai.postprocessing.response_postprocessor import postprocess_response
from app.ai.conversation.handler import ConversationalHandler
from app.ai.copilot.preflight import CopilotPreflight
from app.ai.graph.workflow_graph import WorkflowEntityGraph
from app.ai.memory.policy import MemoryPolicyService
from app.ai.memory.repository import AIRepository
from app.ai.memory.audit import MemoryAuditService
from app.ai.preferences.service import UserPreferenceService
from app.ai.prompts.personality import append_enterprise_tone
from app.ai.prompts.role_prompts import get_allowed_tools_for_role, get_role_prompt_body, get_role_prompt_key
from app.ai.prompts.copilot_interactive import (
    CONVERSATIONAL_OPENAI_SYSTEM,
    SYNTH_AFTER_TOOLS_INSTRUCTION,
    WELCOME_GENERATION_SYSTEM,
    build_welcome_user_prompt,
)
from app.ai.prompts.welcome import CHAT_WELCOME_MESSAGE, WELCOME_MESSAGE_METADATA, is_welcome_message
from app.config import settings
from app.ai.conversation.expense_manage import ExpenseManageWorkflow, detect_manage_action
from app.ai.conversation.state_machine import (
    _POST_SAVE_FOLLOWUP_QUESTION,
)
from app.ai.workflow.engine import WorkflowEngine
from app.ai.schemas.memory import DraftExpenseContext
from app.ai.schemas.workflow import WorkflowType
from app.ai.safety.rules_engine import SafetyRulesEngine
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.schemas.conversation import ConversationMessageCreate
from app.ai.schemas.audit import TokenUsage
from app.ai.schemas.classification import ResponseClassificationOut
from app.ai.schemas.openai_result import ToolCallPlan
from app.ai.models.entities import ConversationRole
from app.ai.services.audit_service import AuditService
from app.ai.services.cost_tracking_service import CostTrackingService
from app.ai.services.memory_service import MemoryService
from app.ai.services.openai_service import OpenAIService
from app.ai.session_lock import SessionLockManager, session_lock, SessionLockError
from app.ai.tools.argument_normalizer import normalize_tool_arguments
from app.services.expense_enrichment_service import ExpenseEnrichmentService
from app.ai.tools.argument_repair import repair_tool_arguments
from app.ai.tools.execution_policy import ToolExecutionPolicy, ToolExecutionDenied
from app.ai.tools.executor import ToolExecutor
from app.ai.tools.handlers import wire_handlers
from app.ai.tools.rate_limiter import ToolRateLimiter
from app.ai.tools.registry import ToolRegistry, default_expense_tool_registry
from app.ai.schemas.tool_result import ToolResult
from app.models import Expense, User

logger = logging.getLogger(__name__)


def _build_confirmation_summary(tool_name: str, arguments: Dict[str, Any]) -> str:
    if tool_name == "expense.submit.v1":
        return f"I can submit expense #{arguments.get('expense_id')} for approval. Do you want me to proceed?"
    if tool_name == "approval.submit.v1":
        return (
            f"I can {arguments.get('decision', 'review')} approval #{arguments.get('approval_id')}. "
            f"Do you want me to proceed?"
        )
    if tool_name == "reimbursement.submit.v1":
        return (
            f"I found a reimbursement for claim #{arguments.get('claim_id')} "
            f"({arguments.get('amount', '?')}). Do you want me to submit it?"
        )
    if tool_name == "expense.delete.v1":
        return f"I can delete expense #{arguments.get('expense_id')}. Do you want me to proceed?"
    if tool_name == "expense.update.v1":
        fields = [k for k in arguments if k != "expense_id"]
        return (
            f"I can update expense #{arguments.get('expense_id')} "
            f"({', '.join(fields) or 'fields'}). Do you want me to proceed?"
        )
    if tool_name == "expense.approval.action.v1":
        action = arguments.get("action", "review")
        return (
            f"I can {action} expense approval step #{arguments.get('approval_id')}. "
            "Do you want me to proceed?"
        )
    if tool_name in ("approval.bulk_approve.v1", "approval.bulk_reject.v1"):
        ids = arguments.get("approval_ids") or []
        action = "approve" if "approve" in tool_name else "reject"
        return (
            f"I will {action} {len(ids)} claim(s). "
            f"This cannot be undone without manual review. Proceed?"
        )
    if tool_name == "escalation.create.v1":
        return (
            f"I will escalate claim #{arguments.get('claim_id')} to "
            f"{arguments.get('target_role', 'finance')}. Proceed?"
        )
    return f"I'm ready to run '{tool_name}'. Do you want me to proceed?"


class AIOrchestrator:
    """Production orchestrator with Phase 3 conversational intelligence hooks."""

    def __init__(
        self,
        db: Session,
        memory_service: MemoryService,
        openai_service: OpenAIService,
        audit_service: AuditService,
        session_lock_manager: SessionLockManager,
        tool_executor: ToolExecutor,
        confirmation_service: ConfirmationService,
        cost_tracking: CostTrackingService,
        dead_letter: Optional[DeadLetterQueueService] = None,
        tool_registry: Optional[ToolRegistry] = None,
        execution_policy: Optional[ToolExecutionPolicy] = None,
        response_classifier: Optional[ResponseClassifier] = None,
        permission_matrix: Optional[ToolPermissionMatrix] = None,
        safety_engine: Optional[SafetyRulesEngine] = None,
        rate_limiter: Optional[ToolRateLimiter] = None,
        context_builder: Optional[ContextBuilder] = None,
        copilot_preflight: Optional[CopilotPreflight] = None,
    ):
        self._db = db
        self._memory = memory_service
        self._openai = openai_service
        self._audit = audit_service
        self._locks = session_lock_manager
        self._executor = tool_executor
        self._confirmation = confirmation_service
        self._cost = cost_tracking
        self._dlq = dead_letter or DeadLetterQueueService(db)
        self._tools = tool_registry or default_expense_tool_registry()
        wire_handlers(self._tools, db)
        self._matrix = permission_matrix or ToolPermissionMatrix(db)
        self._policy = execution_policy or ToolExecutionPolicy(
            registry=self._tools,
            permission_matrix=self._matrix,
        )
        self._classifier = response_classifier or ResponseClassifier()
        self._safety = safety_engine or SafetyRulesEngine()
        self._rate_limiter = rate_limiter or ToolRateLimiter()
        self._intent = IntentDetector()
        self._conversation = ConversationalHandler(intent_detector=self._intent)
        self._workflow = WorkflowEngine(memory_service, db=db)
        self._context_builder = context_builder or ContextBuilder()
        repo = AIRepository(db)
        self._copilot = copilot_preflight or CopilotPreflight(
            db, memory_service, repo, confirmation_service
        )
        self._memory_policy = MemoryPolicyService(db)
        self._preferences = UserPreferenceService(
            db, repo, policy=self._memory_policy, audit=MemoryAuditService(db)
        )
        self._graph = WorkflowEntityGraph(repo, self._memory_policy)
        self._chain_parent_audit_id: Optional[int] = None
        self._last_executed_tools: List[str] = []

    async def handle_user_message(
        self,
        ctx: SessionContext,
        message: str,
        *,
        user: User,
        persist_message: Optional[str] = None,
        llm_user_content: Optional[Union[str, List[Dict[str, Any]]]] = None,
        skip_active_workflow: bool = False,
    ) -> Dict[str, Any]:
        trace = get_or_create_trace_context(session_id=ctx.session_id)
        log_extra = trace.log_extra()
        self._chain_parent_audit_id = None
        self._last_executed_tools = []

        persist = persist_message if persist_message is not None else message
        openai_last_user = llm_user_content if llm_user_content is not None else persist

        try:
            async with session_lock(self._locks, ctx):
                tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
                has_active_workflow = await self._has_active_expense_workflow(ctx)

                intent = self.detect_intent(message)
                manage_action_early = detect_manage_action(message)
                from app.ai.utils.expense_search import is_pending_bills_query

                skip_welcome_for_action = (
                    manage_action_early
                    or is_pending_bills_query(message)
                    or intent.intent
                    in (
                        UserIntent.DELETE_EXPENSE,
                        UserIntent.UPDATE_EXPENSE,
                        UserIntent.CREATE_EXPENSE,
                        UserIntent.SUBMIT_EXPENSE,
                        UserIntent.LIST_PENDING,
                    )
                )

                # Persist the user turn first so welcome / workflow paths never drop it.
                await self.store_memory(
                    ctx,
                    ConversationMessageCreate(
                        role=ConversationRole.USER, content=persist
                    ),
                )

                if (
                    not skip_welcome_for_action
                    and not await self._session_has_welcome(ctx)
                    and not has_active_workflow
                ):
                    await self._ensure_welcome_stored_fast(
                        ctx, user=user, log_extra=log_extra
                    )

                if not skip_active_workflow:
                    workflow_out = await self._continue_active_workflow(
                        ctx, user, message, log_extra
                    )
                    if workflow_out:
                        return workflow_out

                pending_list = await self._try_list_pending_bills(
                    ctx, user, message, persist, log_extra
                )
                if pending_list:
                    return pending_list

                from app.ai.confirmation.affirm import is_submit_confirmation

                if is_submit_confirmation(message) or intent.intent == UserIntent.CONFIRM:
                    pending = self._confirmation.get_latest_pending_for_session(
                        tenant_id=ctx.tenant_id, user_id=user.id, session_id=ctx.session_id
                    )
                    if pending:
                        result = await self.confirm_tool_execution(
                            user=user, ctx=ctx, confirmation_token=pending.confirmation_token
                        )
                        if result.success and pending.tool_name in (
                            "expense.create.v1",
                            "expense.submit.v1",
                        ):
                            return await self._finalize_expense_saved(
                                ctx, user, message, log_extra, result
                            )
                        content = await self.build_response(message, tool_results=[result])
                        return await self._finalize_chat(ctx, user, content, log_extra, tool_results=[result])

                    receipt_draft = await self._memory.get_draft_expense(ctx)
                    if receipt_draft and receipt_draft.expense_id and (
                        is_submit_confirmation(message) or intent.intent == UserIntent.CONFIRM
                    ):
                        result = await self.execute_tool(
                            user=user,
                            ctx=ctx,
                            tool_name="expense.create.v1",
                            arguments=draft_confirm_tool_arguments(receipt_draft),
                            source_user_message=receipt_draft.source_utterance or message,
                        )
                        if result.success:
                            return await self._finalize_expense_saved(
                                ctx, user, message, log_extra, result
                            )
                        content = await self.build_response(message, tool_results=[result])
                        return await self._finalize_chat(
                            ctx, user, content, log_extra, tool_results=[result]
                        )

                if is_denial(message) or intent.intent == UserIntent.DENY:
                    pending = self._confirmation.get_latest_pending_for_session(
                        tenant_id=ctx.tenant_id, user_id=user.id, session_id=ctx.session_id
                    )
                    if pending:
                        self._confirmation.mark_cancelled(
                            pending.confirmation_token, tenant_id=ctx.tenant_id, user_id=user.id
                        )
                        return await self._finalize_chat(ctx, user, "Okay, I've cancelled that action.", log_extra)

                manage_action = detect_manage_action(message)
                wf_state = await self._memory.get_workflow_state(ctx)
                active_manage = bool(
                    wf_state
                    and wf_state.workflow_type
                    in (WorkflowType.EXPENSE_DELETE, WorkflowType.EXPENSE_UPDATE)
                )
                blocked_manage = bool(
                    wf_state
                    and wf_state.workflow_type
                    in (WorkflowType.EXPENSE_CREATE, WorkflowType.EXPENSE_CONTINUE)
                )
                if (
                    manage_action
                    and not active_manage
                    and not blocked_manage
                    and intent.intent
                    in (
                        UserIntent.DELETE_EXPENSE,
                        UserIntent.UPDATE_EXPENSE,
                        UserIntent.GENERAL_CHAT,
                    )
                ):
                        from app.ai.utils.date_range_parser import parse_date_range
                        from app.ai.security import scoped_company_id

                        manage = ExpenseManageWorkflow(self._db)
                        date_hint = message if parse_date_range(message) else None
                        start_result = manage.start(
                            manage_action,
                            session_id=ctx.session_id,
                            user_id=user.id,
                            company_id=scoped_company_id(ctx, user),
                            initial_text=date_hint,
                        )
                        if start_result.handled:
                            if start_result.updated_state:
                                start_result.updated_state.slots["user_id"] = user.id
                                start_result.updated_state.slots["company_id"] = (
                                    scoped_company_id(ctx, user)
                                )
                                start_result.updated_state.session_id = ctx.session_id
                                await self._memory.set_workflow_state(
                                    ctx, start_result.updated_state
                                )
                                await self._workflow.persist_workflow_state(
                                    ctx, start_result.updated_state
                                )
                            if start_result.ready_tool_name:
                                tool_result = await self.execute_tool(
                                    user=user,
                                    ctx=ctx,
                                    tool_name=start_result.ready_tool_name,
                                    arguments=start_result.ready_arguments,
                                    source_user_message=message,
                                )
                                content = await self.build_response(
                                    message, tool_results=[tool_result]
                                )
                                return await self._finalize_chat(
                                    ctx,
                                    user,
                                    content,
                                    log_extra,
                                    tool_results=[tool_result],
                                )
                            if start_result.assistant_message:
                                return await self._finalize_chat(
                                    ctx,
                                    user,
                                    start_result.assistant_message,
                                    log_extra,
                                    metadata={"workflow": manage_action},
                                )

                conv = await self._intercept_conversational(ctx, user, message, log_extra)
                if conv:
                    return conv

                preflight = await self._copilot.run(ctx, user, message)

                if preflight.intercept_message:
                    return await self._finalize_chat(
                        ctx, user, preflight.intercept_message, log_extra
                    )

                if preflight.execute_tool and preflight.execute_arguments:
                    result = await self.execute_tool(
                        user=user,
                        ctx=ctx,
                        tool_name=preflight.execute_tool,
                        arguments=preflight.execute_arguments,
                        source_user_message=message,
                    )
                    content = await self.build_response(message, tool_results=[result])
                    return await self._finalize_chat(
                        ctx, user, content, log_extra, tool_results=[result]
                    )

                memory_ctx = await self.load_memory(
                    ctx, user_query=message, scope=preflight.scope
                )
                system_prompt, prompt_key, tools = self.select_prompt(user)

                pending = self._confirmation.get_latest_pending_for_session(
                    tenant_id=ctx.tenant_id, user_id=user.id, session_id=ctx.session_id
                )
                draft = await self._memory.get_draft_expense(ctx)
                draft_hint = None
                if draft and draft.bill_name:
                    draft_hint = f"{draft.bill_name} {draft.bill_amount or '?'}"
                pending_summary = pending.summary_message if pending else None

                ref_ctx = preflight.reference_context
                if preflight.resolved and preflight.resolved.vendor_name:
                    ref_ctx = (ref_ctx or "") + f" Merchant context: {preflight.resolved.vendor_name}."

                messages = self._context_builder.build_partitioned_messages(
                    system_prompt=system_prompt,
                    context=memory_ctx,
                    pending_confirmation_summary=pending_summary,
                    draft_hint=draft_hint,
                    preference_lines=preflight.preference_lines,
                    workflow_lines=preflight.workflow_lines,
                    reference_context=ref_ctx,
                    pending_intent_summary=preflight.pending_intent_summary,
                    memory_explanations=preflight.memory_explanations,
                )

                messages = replace_last_user_message_content(messages, openai_last_user)

                llm_result = await self._openai.chat_with_tools(messages, tools=tools)
                self._cost.record_chat_usage(tenant_id=ctx.tenant_id, usage=llm_result.token_usage)
                audit_ctx = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
                row = self._audit.log_prompt(
                    audit_ctx,
                    session_id=ctx.session_id,
                    model=llm_result.model,
                    messages_summary={"prompt_key": prompt_key, "tool_calls": len(llm_result.tool_calls)},
                    token_usage=llm_result.token_usage,
                    latency_ms=llm_result.latency_ms,
                )
                if self._chain_parent_audit_id is None:
                    self._chain_parent_audit_id = row.id

                tool_results: List[ToolResult] = []
                if llm_result.tool_calls:
                    plans = await self.plan_tools(llm_result.tool_calls, user=user)
                    for plan in plans:
                        if not self._tools.is_registered(plan.name):
                            tool_results.append(ToolResult.fail(
                                f"Unknown tool: {plan.name}", error="unknown_tool"
                            ))
                            continue
                        args = dict(plan.arguments)
                        if (
                            "submit" in plan.name
                            or "approval.action" in plan.name
                        ) and "idempotency_key" not in args:
                            args["idempotency_key"] = str(uuid.uuid4())
                        result = await self.execute_tool(
                            user=user,
                            ctx=ctx,
                            tool_name=plan.name,
                            arguments=args,
                            source_user_message=message,
                        )
                        tool_results.append(result)
                        if result.requires_confirmation:
                            return await self._finalize_chat(
                                ctx, user, result.message, log_extra,
                                tool_results=tool_results,
                                extra={
                                    "requires_confirmation": True,
                                    "confirmation_token": result.confirmation_token,
                                },
                            )

                synth_content = llm_result.content
                if tool_results and not any(r.requires_confirmation for r in tool_results):
                    synth_messages = self._context_builder.build_partitioned_messages(
                        system_prompt=system_prompt,
                        context=memory_ctx,
                        tool_results=tool_results,
                        pending_confirmation_summary=pending_summary,
                        draft_hint=draft_hint,
                        preference_lines=preflight.preference_lines,
                        workflow_lines=preflight.workflow_lines,
                        reference_context=ref_ctx,
                        memory_explanations=preflight.memory_explanations,
                    )
                    synth_messages.append({
                        "role": "system",
                        "content": SYNTH_AFTER_TOOLS_INSTRUCTION.strip(),
                    })
                    synth_messages.append({"role": "user", "content": openai_last_user})
                    synth = await self._openai.chat_reply(synth_messages)
                    self._cost.record_chat_usage(tenant_id=ctx.tenant_id, usage=synth.token_usage)
                    if synth.content and synth.content.strip():
                        synth_content = synth.content

                content = await self.build_response(
                    message,
                    llm_content=synth_content,
                    tool_results=tool_results,
                )
                return await self._finalize_chat(ctx, user, content, log_extra, tool_results=tool_results)

        except SessionLockError:
            logger.warning("session.lock_denied", extra=log_extra)
            raise
        except RuntimeError as exc:
            if "OPENAI_API_KEY" in str(exc):
                return await self._finalize_chat(
                    ctx,
                    user,
                    "The AI assistant is not configured on the server yet. "
                    "Ask your admin to set OPENAI_API_KEY in the backend environment.",
                    log_extra,
                )
            raise
        except Exception as exc:
            from openai import APIError, APITimeoutError, RateLimitError

            if isinstance(exc, (APIError, APITimeoutError, RateLimitError)):
                logger.exception("openai.chat_failed", extra=log_extra)
                return await self._finalize_chat(
                    ctx,
                    user,
                    "I'm having trouble connecting to the AI service right now. "
                    "Please try again in a moment.",
                    log_extra,
                )
            raise

    def detect_intent(self, user_content: str):
        return self._intent.detect(user_content)

    def _openai_ready(self) -> bool:
        return bool((settings.openai_api_key or "").strip())

    async def _generate_dynamic_welcome(self, user: User) -> Optional[str]:
        if not self._openai_ready() or not settings.openai_dynamic_welcome:
            return None
        display = (getattr(user, "full_name", None) or getattr(user, "username", None) or "").strip()
        first = display.split()[0] if display else "there"
        role_attr = getattr(user, "role", None)
        role = getattr(role_attr, "value", None) or str(role_attr or "employee")
        messages = [
            {
                "role": "system",
                "content": append_enterprise_tone(WELCOME_GENERATION_SYSTEM.strip()),
            },
            {
                "role": "user",
                "content": build_welcome_user_prompt(
                    display_name=first,
                    role_label=role.replace("_", " "),
                ),
            },
        ]
        try:
            result = await self._openai.chat_reply(messages, temperature=0.65)
            text = (result.content or "").strip()
            if len(text) >= 20:
                return text
        except Exception:
            logger.warning("openai.welcome_failed", exc_info=True)
        return None

    async def _openai_conversational_reply(
        self,
        user_text: str,
        *,
        conv_intent: ConversationIntentType,
        preferred_name: Optional[str],
        recent_messages: List[Any],
    ) -> Optional[str]:
        if not self._openai_ready() or not settings.openai_conversational_enabled:
            return None
        system = append_enterprise_tone(CONVERSATIONAL_OPENAI_SYSTEM.strip())
        if preferred_name:
            system += f"\nUser preferred name: {preferred_name}."
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        for msg in recent_messages[-8:]:
            role = getattr(msg, "role", None)
            content = (getattr(msg, "content", None) or "").strip()
            meta = getattr(msg, "metadata", None) or {}
            if not content or meta.get("welcome") or is_welcome_message(content, meta):
                continue
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content})
        if not messages or messages[-1].get("role") != "user":
            messages.append({"role": "user", "content": user_text})
        try:
            result = await self._openai.chat_reply(messages, temperature=0.65)
            text = (result.content or "").strip()
            return text if text else None
        except Exception:
            logger.warning(
                "openai.conversational_failed intent=%s",
                conv_intent.value,
                exc_info=True,
            )
            return None

    async def _intercept_conversational(
        self,
        ctx: SessionContext,
        user: User,
        user_content: str,
        log_extra: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Fast path for greetings and small talk — runs before preflight, memory load,
        OpenAI, and tool planning. No preferred_name in templates until memory is verified.
        """
        text = (user_content or "").strip()
        if not text:
            return None

        recent = await self._memory.fetch_recent_context(ctx, limit=12)
        user_lines = [m.content for m in recent.messages if m.role == "user"]
        assistant_lines = [
            m.content
            for m in recent.messages
            if m.role == "assistant"
            and not (m.metadata or {}).get("welcome")
            and m.content != CHAT_WELCOME_MESSAGE
        ]
        last_assistant = assistant_lines[-1] if assistant_lines else None

        conv_intent = self._intent.detect_conversation(
            text, last_assistant_message=last_assistant
        )
        if conv_intent == ConversationIntentType.NONE:
            logger.debug(
                "conversational.miss",
                extra={
                    **log_extra,
                    "user_id": ctx.user_id,
                    "tenant_id": ctx.tenant_id,
                    "preview": text[:80],
                },
            )
            return None

        preferred = self._preferences.get_preferred_name(
            TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        )
        openai_reply = await self._openai_conversational_reply(
            text,
            conv_intent=conv_intent,
            preferred_name=preferred,
            recent_messages=recent.messages,
        )
        if openai_reply:
            return await self._finalize_chat(
                ctx,
                user,
                openai_reply,
                log_extra,
                metadata={"conversational": True, "intent": conv_intent.value, "openai": True},
            )

        turn = self._conversation.try_reply(
            text,
            preferred_name=preferred,
            recent_user_messages=user_lines,
            recent_assistant_messages=assistant_lines,
        )
        if not turn.handled or not turn.message:
            logger.warning(
                "conversational.intent_without_template",
                extra={**log_extra, "intent": conv_intent.value},
            )
            return None

        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        if turn.learned_name:
            self._preferences.set_preferred_name(tu, turn.learned_name)
            logger.info(
                "conversational.learned_name name=%s user_id=%s tenant_id=%s",
                turn.learned_name,
                ctx.user_id,
                ctx.tenant_id,
            )

        logger.info(
            "conversational.intercept intent=%s user_id=%s tenant_id=%s",
            conv_intent.value,
            ctx.user_id,
            ctx.tenant_id,
        )

        return await self._finalize_chat(
            ctx,
            user,
            turn.message,
            log_extra,
            metadata={"conversational": True, "intent": conv_intent.value},
        )

    async def _has_active_expense_workflow(self, ctx: SessionContext) -> bool:
        state, draft, pending = await self._workflow.get_active_context(ctx)
        if state is not None:
            if state.workflow_type in (
                WorkflowType.EXPENSE_DELETE,
                WorkflowType.EXPENSE_UPDATE,
            ):
                return True
            if state.workflow_type in (
                WorkflowType.EXPENSE_CREATE,
                WorkflowType.EXPENSE_CONTINUE,
            ):
                return True
        if pending and pending.intent_type == "expense_create":
            return True
        if draft and (draft.fields_pending or draft.bill_amount or draft.vendor_name):
            return True
        return False

    async def _try_list_pending_bills(
        self,
        ctx: SessionContext,
        user: User,
        message: str,
        persist: str,
        log_extra: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        from app.ai.utils.expense_search import is_pending_bills_query

        if not is_pending_bills_query(message):
            return None

        result = await self.execute_tool(
            user=user,
            ctx=ctx,
            tool_name="expense.search.v1",
            arguments={"status": "pending", "limit": 50},
            source_user_message=message,
        )
        content = await self.build_response(message, tool_results=[result])
        return await self._finalize_chat(
            ctx, user, content, log_extra, tool_results=[result]
        )

    async def _continue_active_workflow(
        self,
        ctx: SessionContext,
        user: User,
        user_content: str,
        log_extra: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        import asyncio

        from app.ai.resolution.reference_resolver import ReferenceResolver, needs_expense_history
        from app.ai.security import scoped_company_id

        state, draft, pending = await self._workflow.get_active_context(ctx)
        has_active = state is not None
        if not has_active and draft and (
            draft.fields_pending or self._workflow._draft_incomplete(draft)
        ):
            has_active = True
        if not has_active and pending and pending.intent_type == "expense_create":
            has_active = True
        if not has_active:
            return None

        company_id = scoped_company_id(ctx, user)
        prefill: Dict[str, Any] = {}
        if needs_expense_history(user_content):
            resolved = await asyncio.to_thread(
                ReferenceResolver(self._db).resolve,
                user.id,
                user_content,
                company_id=company_id,
            )
            prefill = resolved.apply_to_slots({})

        result = await self._workflow.continue_workflow(
            ctx, user_content, prefill=prefill, user=user
        )
        if not result.handled:
            return None

        if result.execute_tool:
            tool_result = await self.execute_tool(
                user=user,
                ctx=ctx,
                tool_name=result.execute_tool,
                arguments=result.execute_arguments,
                source_user_message=user_content,
            )
            if (
                tool_result.success
                and result.execute_tool in ("expense.create.v1", "expense.submit.v1")
            ):
                return await self._finalize_expense_saved(
                    ctx, user, user_content, log_extra, tool_result
                )
            content = await self.build_response(user_content, tool_results=[tool_result])
            return await self._finalize_chat(
                ctx, user, content, log_extra, tool_results=[tool_result]
            )

        if result.message:
            logger.info(
                "workflow.intercept session_id=%s user_id=%s",
                ctx.session_id,
                ctx.user_id,
                extra=log_extra,
            )
            extra = {}
            if result.ui_actions:
                extra["ui_actions"] = result.ui_actions
                extra["attachments_enabled"] = any(
                    getattr(a, "action", None) == "attach"
                    for a in result.ui_actions
                )
            if result.expense_previews:
                extra["expense_previews"] = result.expense_previews
            if getattr(result, "category_picker", None):
                extra["category_picker"] = result.category_picker
            return await self._finalize_chat(
                ctx,
                user,
                result.message,
                log_extra,
                metadata={"workflow": True},
                extra=extra,
            )
        return None

    async def _session_has_welcome(self, ctx: SessionContext) -> bool:
        return await self._get_welcome_message(ctx) is not None

    async def _get_welcome_message(self, ctx: SessionContext):
        recent = await self._memory.fetch_recent_context(ctx, limit=30)
        for msg in reversed(recent.messages):
            if is_welcome_message(msg.content, msg.metadata):
                return msg
        return None

    async def ensure_session_welcome(self, ctx: SessionContext, *, user: User) -> Dict[str, Any]:
        """Return the fixed Bizwy welcome for this session (idempotent)."""
        async with session_lock(self._locks, ctx):
            return await self._deliver_session_welcome(ctx, user=user)

    async def _ensure_welcome_stored(
        self,
        ctx: SessionContext,
        *,
        user: User,
        log_extra: Dict[str, Any],
        fast: bool = False,
    ) -> None:
        """Persist session welcome in memory (OpenAI-generated when configured)."""
        if await self._session_has_welcome(ctx):
            return
        if fast:
            await self._ensure_welcome_stored_fast(ctx, user=user, log_extra=log_extra)
            return
        welcome_text = CHAT_WELCOME_MESSAGE
        meta = dict(WELCOME_MESSAGE_METADATA)
        dynamic = await self._generate_dynamic_welcome(user)
        if dynamic:
            welcome_text = dynamic
            meta["openai"] = True
        await self._finalize_chat(
            ctx,
            user,
            welcome_text,
            log_extra,
            metadata=meta,
            for_user_turn=False,
        )

    async def _ensure_welcome_stored_fast(
        self,
        ctx: SessionContext,
        *,
        user: User,
        log_extra: Dict[str, Any],
    ) -> None:
        """Store welcome without blocking the current user turn or returning early."""
        if await self._session_has_welcome(ctx):
            return
        if settings.openai_dynamic_welcome and self._openai_ready():
            asyncio.create_task(
                self._store_welcome_background(ctx, user, log_extra)
            )
            return
        await self.store_memory(
            ctx,
            ConversationMessageCreate(
                role=ConversationRole.ASSISTANT,
                content=CHAT_WELCOME_MESSAGE,
                metadata=dict(WELCOME_MESSAGE_METADATA),
            ),
        )

    async def _store_welcome_background(
        self,
        ctx: SessionContext,
        user: User,
        log_extra: Dict[str, Any],
    ) -> None:
        """Generate and store dynamic welcome without blocking chat replies."""
        try:
            if await self._session_has_welcome(ctx):
                return
            dynamic = await self._generate_dynamic_welcome(user)
            welcome_text = dynamic if dynamic else CHAT_WELCOME_MESSAGE
            meta = dict(WELCOME_MESSAGE_METADATA)
            if dynamic:
                meta["openai"] = True
            await self.store_memory(
                ctx,
                ConversationMessageCreate(
                    role=ConversationRole.ASSISTANT,
                    content=welcome_text,
                    metadata=meta,
                ),
            )
        except Exception as exc:
            logger.warning(
                "background_welcome_failed: %s",
                exc,
                extra=log_extra,
            )
            if not await self._session_has_welcome(ctx):
                await self.store_memory(
                    ctx,
                    ConversationMessageCreate(
                        role=ConversationRole.ASSISTANT,
                        content=CHAT_WELCOME_MESSAGE,
                        metadata=dict(WELCOME_MESSAGE_METADATA),
                    ),
                )

    async def end_session(self, ctx: SessionContext, *, user: User) -> None:
        """Clear ephemeral session state (Redis + scoped workflow/draft memory)."""
        state = await self._memory.get_workflow_state(ctx)
        if state and self._db and state.slots.get("bill_amount"):
            try:
                from app.ai.workflow.draft_persist import persist_workflow_draft

                persist_workflow_draft(
                    self._db, user, state, company_id=ctx.scoped_company_id
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                logger.exception(
                    "end_session_draft_persist_failed session_id=%s",
                    ctx.session_id,
                )
        await self._memory.clear_session_state(ctx)
        await self._memory.mark_chat_session_inactive(ctx)
        pending = self._confirmation.get_latest_pending_for_session(
            tenant_id=ctx.tenant_id, user_id=user.id, session_id=ctx.session_id
        )
        if pending:
            self._confirmation.mark_cancelled(
                pending.confirmation_token,
                tenant_id=ctx.tenant_id,
                user_id=user.id,
            )

    async def _deliver_session_welcome(self, ctx: SessionContext, *, user: User) -> Dict[str, Any]:
        trace = get_or_create_trace_context(session_id=ctx.session_id)
        log_extra = trace.log_extra()
        existing = await self._get_welcome_message(ctx)
        if existing is not None:
            return self._welcome_response(ctx, existing, log_extra)
        await self._ensure_welcome_stored(ctx, user=user, log_extra=log_extra)
        stored = await self._get_welcome_message(ctx)
        if stored is not None:
            return self._welcome_response(ctx, stored, log_extra)
        return await self._finalize_chat(
            ctx,
            user,
            CHAT_WELCOME_MESSAGE,
            log_extra,
            metadata=WELCOME_MESSAGE_METADATA,
            for_user_turn=False,
        )

    def _welcome_response(
        self, ctx: SessionContext, message, log_extra: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "message": message,
            "session_id": ctx.session_id,
            "request_id": log_extra.get("request_id"),
            "trace_id": log_extra.get("trace_id"),
            "classification": ResponseClassificationOut(
                classification=ResponseClassification.SAFE,
                confidence=1.0,
                reasons=["welcome_message"],
            ),
        }

    async def load_memory(self, ctx: SessionContext, *, user_query: str = "", scope=None):
        from app.ai.schemas.workflow import WorkflowScope
        raw = await self._memory.fetch_recent_context(ctx)
        pending = self._confirmation.get_latest_pending_for_session(
            tenant_id=ctx.tenant_id, user_id=ctx.user_id, session_id=ctx.session_id
        )
        return self._context_builder.rank_context(
            raw,
            user_query=user_query,
            has_pending_confirmation=bool(pending),
            scope=scope or WorkflowScope.GENERAL,
        )

    def select_prompt(self, user: User) -> tuple[str, str, List[Dict[str, Any]]]:
        prompt_key = get_role_prompt_key(user.role)
        body = append_enterprise_tone(get_role_prompt_body(user.role))
        allowed = get_allowed_tools_for_role(user.role)
        tools = self._tools.list_openai_tools(allowed_names=allowed)
        return body, prompt_key, tools

    async def plan_tools(self, tool_calls: List[ToolCallPlan], *, user: User) -> List[ToolCallPlan]:
        allowed = get_allowed_tools_for_role(user.role)
        plans: List[ToolCallPlan] = []
        for tc in tool_calls[:5]:
            resolved = self._tools.resolve_name(tc.name)
            if resolved not in allowed and tc.name not in allowed:
                continue
            if not self._tools.is_registered(tc.name):
                continue
            tool_def = self._tools.get(tc.name)
            repair = repair_tool_arguments(
                resolved,
                normalize_tool_arguments(tc.arguments),
                tool_def.parameters_schema if tool_def else {},
            )
            if not repair.valid:
                logger.warning(
                    "plan_tools.repair_failed",
                    extra={"tool": resolved, "errors": repair.errors},
                )
                continue
            plans.append(ToolCallPlan(id=tc.id, name=resolved, arguments=repair.arguments))
        return plans

    async def build_response(
        self,
        user_content: str,
        *,
        llm_content: str = "",
        tool_results: Optional[List[ToolResult]] = None,
    ) -> str:
        tool_results = tool_results or []
        if tool_results:
            for r in tool_results:
                if r.requires_confirmation:
                    return r.message
                if r.error == "missing_amount":
                    return r.message
                if r.error in ("invalid_sub_category", "invalid_arguments") and r.message:
                    return r.message
                if r.error == "tool_error" and r.message and "sub_category" in r.message.lower():
                    from app.ai.workflow.slot_parser import food_sub_category_prompt

                    return food_sub_category_prompt()
            if llm_content and llm_content.strip():
                raw = llm_content.strip()
            else:
                parts = [r.message for r in tool_results if r.message]
                raw = " ".join(parts) if parts else "Sure — what would you like to do next?"
        else:
            raw = llm_content.strip() if llm_content else (
                "Sure — what would you like to do next?"
            )

        safety_flags: List[str] = []
        for r in tool_results:
            safety_flags.extend(r.safety_flags or [])

        processed, _meta = postprocess_response(
            raw,
            tool_results=tool_results,
            executed_tool_names=self._last_executed_tools,
            policy_hints=safety_flags,
        )
        return processed

    async def store_memory(self, ctx: SessionContext, message: ConversationMessageCreate):
        return await self._memory.save_conversation(ctx, message)

    async def confirm_tool_execution(
        self, *, user: User, ctx: SessionContext, confirmation_token: str
    ) -> ToolResult:
        pending = self._confirmation.get_pending(
            confirmation_token, tenant_id=ctx.tenant_id, user_id=user.id
        )
        if not pending:
            return ToolResult.fail("Confirmation expired or not found.", error="invalid_confirmation")
        self._confirmation.mark_confirmed(pending)
        if not pending.arguments.get("idempotency_key") and "submit" in pending.tool_name:
            pending.arguments["idempotency_key"] = str(uuid.uuid4())
        source_msg = await self._last_substantive_user_message(ctx)
        return await self.execute_tool(
            user=user,
            ctx=ctx,
            tool_name=pending.tool_name,
            arguments=pending.arguments,
            skip_confirmation=True,
            confirmation_acknowledged=True,
            source_user_message=source_msg,
        )

    async def execute_tool(
        self,
        *,
        user: User,
        ctx: SessionContext,
        tool_name: str,
        arguments: Dict[str, Any],
        parameter_model: Optional[type] = None,
        skip_confirmation: bool = False,
        confirmation_acknowledged: bool = False,
        source_user_message: Optional[str] = None,
    ) -> ToolResult:
        tool_def = self._tools.get(tool_name)
        if tool_def is None:
            return ToolResult.fail(f"Unknown tool: {tool_name}", error="unknown_tool")

        repair = repair_tool_arguments(
            tool_def.name,
            arguments,
            tool_def.parameters_schema,
        )
        if not repair.valid:
            return ToolResult.fail(
                "; ".join(repair.errors) or "Invalid tool arguments",
                error="invalid_arguments",
                data={"repairs_attempted": repair.repairs},
            )
        arguments = repair.arguments

        if tool_def.name == "expense.create.v1":
            arguments = await self._enrich_expense_create_arguments(
                ctx, arguments, source_user_message=source_user_message
            )

        try:
            clean_args = self._policy.begin_chain().validate(
                user=user, ctx=ctx, tool_name=tool_name, arguments=arguments,
                parameter_model=parameter_model,
            )
        except ToolExecutionDenied as exc:
            return ToolResult.fail(exc.reason, error=exc.code)

        if tool_def.name == "expense.create.v1":
            clean_args = await self._merge_receipt_draft_into_create(ctx, clean_args)
            # Chat NL flow submits for approval; only keep draft when explicitly updating OCR row.
            if not clean_args.get("expense_id"):
                clean_args["save_as_draft"] = False
            elif clean_args.get("save_as_draft") is None:
                clean_args["save_as_draft"] = False

        allowed, rate_msg = self._rate_limiter.check_and_record(
            tenant_id=ctx.tenant_id, user_id=user.id, tool_name=tool_def.name
        )
        if not allowed:
            return ToolResult.fail(rate_msg or "Rate limited", error="rate_limited")

        from app.intelligence.voice.safety import VoiceCommandSafety
        from app.intelligence.voice.session_flags import VoiceSessionFlags

        voice_meta = await VoiceSessionFlags.get_metadata(ctx)
        voice_originated = VoiceCommandSafety.is_voice_session(voice_meta)
        voice_err = VoiceCommandSafety.validate_tool_allowed(
            tool_def.name,
            voice_originated=voice_originated,
            skip_confirmation=skip_confirmation,
            confirmation_acknowledged=confirmation_acknowledged,
        )
        if voice_err:
            return ToolResult.fail(voice_err, error="voice_safety_block")

        if voice_originated and VoiceCommandSafety.must_force_confirmation(
            tool_def.name, voice_originated=True
        ):
            skip_confirmation = False

        from app.manager.safety import ManagerExecutionSafety

        preview_only = bool(clean_args.get("preview_only", True))
        mgr_err = ManagerExecutionSafety.validate_tool_allowed(
            tool_def.name,
            skip_confirmation=skip_confirmation,
            confirmation_acknowledged=confirmation_acknowledged,
            preview_only=preview_only,
        )
        if mgr_err:
            return ToolResult.fail(mgr_err, error="manager_safety_block")
        bypass = ManagerExecutionSafety.blocks_risk_bypass(tool_def.name, clean_args)
        if bypass:
            return ToolResult.fail(bypass, error="manager_safety_block")

        safety = self._safety.evaluate(tool_name=tool_def.name, arguments=clean_args)
        if safety.block:
            return ToolResult.fail(safety.message or "Blocked", error="safety_block")

        needs_confirm = self._policy.needs_confirmation(tool_def.name)
        if tool_def.name in ("approval.bulk_approve.v1", "approval.bulk_reject.v1") and preview_only:
            needs_confirm = False

        if needs_confirm and not skip_confirmation:
            summary = _build_confirmation_summary(tool_def.name, clean_args)
            if safety.escalate and safety.message:
                summary = f"{safety.message}\n\n{summary}"
            row = self._confirmation.create_pending(
                tenant_id=ctx.tenant_id,
                user_id=user.id,
                session_id=ctx.session_id,
                tool_name=tool_def.name,
                arguments=clean_args,
                summary_message=summary,
            )
            if "submit" in tool_def.name:
                from app.ai.schemas.workflow import (
                    ConversationWorkflowState,
                    WorkflowScope,
                    WorkflowType,
                )
                await self._memory.set_workflow_state(
                    ctx,
                    ConversationWorkflowState(
                        workflow_type=WorkflowType.EXPENSE_SUBMIT,
                        scope=WorkflowScope.EXPENSE,
                        expense_id=clean_args.get("expense_id"),
                        slots={"expense_id": clean_args.get("expense_id")},
                        pending_slots=[],
                        session_id=ctx.session_id,
                    ),
                )
            return ToolResult.pending_confirmation(
                summary,
                confirmation_token=row.confirmation_token,
                data={"tool_name": tool_def.name},
                safety_flags=safety.flags,
            )

        if tool_def.handler is None:
            return ToolResult.fail("Handler not wired", error="handler_not_implemented")

        audit_ctx = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        audit_row = self._audit.log_tool_call(
            audit_ctx,
            session_id=ctx.session_id,
            tool_name=tool_def.name,
            arguments=clean_args,
            parent_audit_id=self._chain_parent_audit_id,
        )
        audit_id = str(audit_row.id)
        self._cost.record_tool_invocation(tenant_id=ctx.tenant_id)

        result = await self._executor.execute(
            tool_name=tool_def.name,
            handler=tool_def.handler,
            user=user,
            ctx=ctx,
            arguments=clean_args,
            idempotency_key=clean_args.get("idempotency_key"),
            action_type=tool_def.logical_name,
        )
        self._last_executed_tools.append(tool_def.name)

        if result.success:
            await self._enrich_memory_after_tool(user, ctx, tool_def.name, result, clean_args)

        if not result.success and self._dlq.should_enqueue(tool_def.name):
            trace = get_trace_context()
            self._dlq.enqueue(
                tenant_id=ctx.tenant_id,
                user_id=user.id,
                session_id=ctx.session_id,
                job_type=tool_def.name,
                payload={"arguments": clean_args, "result": result.model_dump()},
                error_message=result.error or result.message,
                trace_id=trace.trace_id if trace else None,
                request_id=trace.request_id if trace else None,
            )

        return result.model_copy(
            update={
                "audit_id": audit_id,
                "safety_flags": safety.flags,
                "tool": tool_def.name,
            }
        )

    async def _last_substantive_user_message(self, ctx: SessionContext) -> Optional[str]:
        """Last user turn that is not a short confirmation (for tool re-enrichment on confirm)."""
        from app.ai.models.entities import ConversationRole

        _short = frozenset(
            {"yes", "yeah", "yep", "ok", "okay", "confirm", "confirmed", "sure", "proceed", "go ahead"}
        )
        recent = await self._memory.fetch_recent_context(ctx, limit=12)
        for msg in reversed(recent.messages):
            if msg.role != ConversationRole.USER:
                continue
            text = (msg.content or "").strip()
            if len(text) > 12 and text.lower() not in _short:
                return text
        return None

    async def _enrich_expense_create_arguments(
        self,
        ctx: SessionContext,
        arguments: Dict[str, Any],
        *,
        source_user_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        user_message: Optional[str] = None
        recent = await self._memory.fetch_recent_context(ctx, limit=8)
        from app.ai.models.entities import ConversationRole

        for msg in reversed(recent.messages):
            if msg.role == ConversationRole.USER:
                user_message = msg.content
                break

        workflow_slots: Dict[str, Any] = {}
        wf = await self._memory.get_workflow_state(ctx)
        if wf and wf.slots:
            workflow_slots = dict(wf.slots)
        draft = await self._memory.get_draft_expense(ctx)
        if draft:
            if draft.vendor_name and not workflow_slots.get("vendor_name"):
                workflow_slots["vendor_name"] = draft.vendor_name
            if draft.bill_amount is not None and workflow_slots.get("bill_amount") is None:
                workflow_slots["bill_amount"] = draft.bill_amount
            if draft.main_category and not workflow_slots.get("main_category"):
                workflow_slots["main_category"] = draft.main_category
            if draft.bill_name and not workflow_slots.get("bill_name"):
                workflow_slots["bill_name"] = draft.bill_name
            if draft.payment_method and not workflow_slots.get("payment_method"):
                workflow_slots["payment_method"] = draft.payment_method

        source_utterance = source_user_message
        if draft and draft.source_utterance:
            source_utterance = draft.source_utterance
        elif workflow_slots.get("description") and not source_utterance:
            source_utterance = str(workflow_slots["description"])

        svc = ExpenseEnrichmentService(openai_service=self._openai)
        enriched = await svc.enrich_tool_arguments(
            arguments,
            user_message=user_message,
            source_utterance=source_utterance,
            workflow_slots=workflow_slots or None,
        )
        logger.info("expense.create orchestrator enriched=%s", enriched)
        return enriched

    async def _merge_receipt_draft_into_create(
        self, ctx: SessionContext, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """When session memory holds an OCR draft, never create a second expense row."""
        draft = await self._memory.get_draft_expense(ctx)
        if not draft or not draft.expense_id:
            return arguments
        merged = dict(arguments)
        if not merged.get("expense_id"):
            merged["expense_id"] = draft.expense_id
        token = (draft.raw_ocr_hints or {}).get("review_token")
        if token and not merged.get("review_token"):
            merged["review_token"] = token
        if merged.get("bill_amount") is None and draft.bill_amount is not None:
            merged["bill_amount"] = draft.bill_amount
        trusted_vendor = resolve_vendor_from_draft(draft)
        if trusted_vendor:
            merged["vendor_name"] = trusted_vendor
        elif merged.get("vendor_name") and looks_like_chat_command(merged["vendor_name"]):
            merged.pop("vendor_name", None)
        if not merged.get("main_category") and draft.main_category:
            merged["main_category"] = draft.main_category
        return merged

    async def _enrich_memory_after_tool(
        self,
        user: User,
        ctx: SessionContext,
        tool_name: str,
        result: ToolResult,
        arguments: Dict[str, Any],
    ) -> None:
        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        data = result.data or {}
        expense_id = data.get("expense_id")
        from app.ai.security import scoped_company_id

        company_id = scoped_company_id(ctx, user)
        if tool_name == "expense.create.v1" and expense_id:
            expense = (
                self._db.query(Expense)
                .filter(
                    Expense.id == expense_id,
                    Expense.user_id == user.id,
                    Expense.company_id == company_id,
                )
                .first()
            )
            if expense:
                self._preferences.learn_from_expense(tu, expense, source=tool_name)
                self._graph.link_expense(tu, expense, workflow_state="draft")
                await self._memory.set_draft_expense(
                    ctx,
                    DraftExpenseContext(
                        expense_id=expense.id,
                        bill_name=expense.bill_name,
                        bill_amount=expense.bill_amount,
                        vendor_name=expense.vendor_name,
                        main_category=expense.main_category.value if expense.main_category else None,
                        sub_category=expense.sub_category,
                        fields_pending=[],
                    ),
                )
                await self._memory.clear_workflow_state(ctx)
        elif tool_name == "expense.submit.v1" and expense_id:
            expense = (
                self._db.query(Expense)
                .filter(
                    Expense.id == expense_id,
                    Expense.user_id == user.id,
                    Expense.company_id == company_id,
                )
                .first()
            )
            if expense:
                self._preferences.learn_from_expense(tu, expense, source=tool_name)
                self._graph.link_expense(tu, expense, workflow_state="pending")
                await self._memory.clear_draft_expense(ctx)

    async def _finalize_expense_saved(
        self,
        ctx: SessionContext,
        user: User,
        user_message: str,
        log_extra: Dict[str, Any],
        tool_result: ToolResult,
    ) -> Dict[str, Any]:
        extra: Dict[str, Any] = {}
        eid = (tool_result.data or {}).get("expense_id")
        if eid:
            from app.ai.schemas.chat_ui import post_submit_actions
            from app.ai.chat_ui import build_workflow_preview_card
            from app.ai.security import scoped_company_id

            extra["ui_actions"] = post_submit_actions(int(eid))
            card = build_workflow_preview_card(
                self._db,
                expense_id=int(eid),
                slots={
                    "company_id": scoped_company_id(ctx, user),
                    "user_id": user.id,
                },
            )
            if card:
                extra["expense_previews"] = [card]
        await self._memory.clear_draft_expense(ctx)
        await self._memory.clear_pending_intent(ctx)
        await self._memory.set_workflow_state(
            ctx,
            self._workflow.post_save_followup_state(session_id=ctx.session_id),
        )
        content = (tool_result.message or "").strip() or _POST_SAVE_FOLLOWUP_QUESTION
        return await self._finalize_chat(
            ctx,
            user,
            content,
            log_extra,
            tool_results=[tool_result],
            extra=extra,
        )

    async def _finalize_chat(
        self,
        ctx: SessionContext,
        user: User,
        content: str,
        log_extra: Dict[str, Any],
        *,
        tool_results: Optional[List[ToolResult]] = None,
        extra: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        for_user_turn: bool = True,
    ) -> Dict[str, Any]:
        classified = self._classifier.classify(content)
        if classified.classification == ResponseClassification.BLOCKED:
            content = "I can't help with that request. Try rephrasing, or ask me something else."

        meta = dict(metadata or {})
        if (
            for_user_turn
            and is_welcome_message(content, meta)
            and not meta.get("welcome")
        ):
            logger.warning(
                "chat.welcome_leak_replaced session_id=%s user_id=%s",
                ctx.session_id,
                ctx.user_id,
                extra=log_extra,
            )
            content = (
                "Hi! How can I help with your expenses, approvals, or receipts today?"
            )

        assistant = await self.store_memory(
            ctx,
            ConversationMessageCreate(
                role=ConversationRole.ASSISTANT,
                content=content,
                metadata=meta,
            ),
        )

        audit_ctx = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        self._audit.log_response(
            audit_ctx,
            session_id=ctx.session_id,
            model=self._openai.model,
            response_preview=content,
            token_usage=TokenUsage(),
            latency_ms=0,
            parent_audit_id=self._chain_parent_audit_id,
        )

        out: Dict[str, Any] = {
            "message": assistant,
            "session_id": ctx.session_id,
            "request_id": log_extra.get("request_id"),
            "trace_id": log_extra.get("trace_id"),
            "classification": ResponseClassificationOut(
                classification=classified.classification,
                confidence=classified.confidence,
                reasons=classified.reasons,
            ),
        }
        if tool_results:
            out["tool_results"] = [r.model_dump(mode="json") for r in tool_results]
        if extra:
            out.update(extra)
        if meta.get("welcome"):
            out["classification"] = ResponseClassificationOut(
                classification=ResponseClassification.SAFE,
                confidence=1.0,
                reasons=["welcome_message"],
            )
        return out
