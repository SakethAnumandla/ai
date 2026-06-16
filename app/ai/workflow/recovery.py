"""Safe workflow recovery after timeout or interrupted submit — no blind continuation."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.conversation.expense_intent import describes_new_expense
from app.ai.confirmation.service import ConfirmationService
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.schemas.memory_intelligence import WorkflowRecoveryAssessment, WorkflowRecoveryScenario
from app.ai.schemas.workflow import ConversationWorkflowState, WorkflowType
from app.ai.services.memory_service import MemoryService
from app.config import settings
from app.models import Expense, ExpenseStatus


class WorkflowRecoveryService:
    """
    Detect interrupted workflows and return safe recovery prompts
    instead of blindly resuming slot-filling or submit.
    """

    def __init__(
        self,
        db: Session,
        memory: MemoryService,
        confirmation: ConfirmationService,
    ):
        self._db = db
        self._memory = memory
        self._confirmation = confirmation

    def _interrupt_threshold(self) -> timedelta:
        return timedelta(seconds=settings.ai_workflow_interrupt_seconds)

    def _is_stale(self, updated_at: datetime) -> bool:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - updated_at
        return age > self._interrupt_threshold()

    async def assess(
        self,
        ctx: SessionContext,
        *,
        user_text: Optional[str] = None,
        explicit_continue: bool = False,
        intent=None,
    ) -> WorkflowRecoveryAssessment:
        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        state = await self._memory.get_workflow_state(ctx)
        draft = await self._memory.get_draft_expense(ctx)

        pending_confirm = self._confirmation.get_latest_pending_for_session(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
        )
        expired_confirm = self._confirmation.get_latest_expired_for_session(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
        )

        if expired_confirm and not pending_confirm and not explicit_continue:
            tool = expired_confirm.tool_name or "action"
            return WorkflowRecoveryAssessment(
                scenario=WorkflowRecoveryScenario.EXPIRED_CONFIRMATION,
                safe_prompt=(
                    f"Your earlier confirmation for {tool.replace('.', ' ')} has expired. "
                    "I will not proceed automatically. Would you like to try that action again, "
                    "or cancel and continue with something else?"
                ),
                options=["retry", "cancel", "other"],
                context={"tool_name": expired_confirm.tool_name, "expired": True},
                block_blind_resume=True,
            )

        if state and self._is_stale(state.updated_at):
            if state.workflow_type == WorkflowType.EXPENSE_SUBMIT:
                return self._interrupted_submit(ctx, state, draft, explicit_continue)
            return self._stale_slot_filling(state, draft, explicit_continue)

        if draft and not state and not explicit_continue:
            if user_text and describes_new_expense(user_text, intent=intent):
                return WorkflowRecoveryAssessment(scenario=WorkflowRecoveryScenario.NONE)
            if user_text and self._should_skip_ambiguous_draft_prompt(user_text, intent):
                return WorkflowRecoveryAssessment(scenario=WorkflowRecoveryScenario.NONE)

            db_draft = self._latest_db_draft(ctx.user_id, ctx.scoped_company_id)
            if db_draft and self._draft_is_stale(db_draft):
                return WorkflowRecoveryAssessment(
                    scenario=WorkflowRecoveryScenario.AMBIGUOUS_DRAFT,
                    safe_prompt=(
                        f"I found an older draft expense '{db_draft.bill_name}' "
                        f"(₹{db_draft.bill_amount:,.0f}). "
                        "Would you like to continue that draft, submit it, or start a new expense?"
                    ),
                    options=["continue", "submit", "new"],
                    context={"expense_id": db_draft.id},
                    block_blind_resume=True,
                )

        return WorkflowRecoveryAssessment(scenario=WorkflowRecoveryScenario.NONE)

    def _should_skip_ambiguous_draft_prompt(self, text: str, intent) -> bool:
        """Do not block recall, search, or general questions with stale-draft prompts."""
        import re

        from app.ai.orchestrator.intent import UserIntent, is_conversational_message

        if is_conversational_message(text):
            return True

        lowered = text.strip().lower()
        if intent is not None and getattr(intent, "intent", None) in (
            UserIntent.SEARCH_EXPENSE,
            UserIntent.GENERAL_CHAT,
            UserIntent.ANALYTICS,
            UserIntent.LIST_PENDING,
        ):
            return True
        if re.search(
            r"\b(what did i|what did you|tell me|remember|recall|show my|list my|pending)\b",
            lowered,
        ):
            return True
        return False

    def _latest_db_draft(self, user_id: int, company_id: int) -> Optional[Expense]:
        return (
            self._db.query(Expense)
            .filter(
                Expense.user_id == user_id,
                Expense.company_id == company_id,
                Expense.status == ExpenseStatus.DRAFT,
            )
            .order_by(Expense.updated_at.desc())
            .first()
        )

    def _draft_is_stale(self, expense: Expense) -> bool:
        ref = expense.updated_at or expense.created_at
        if not ref:
            return False
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ref > self._interrupt_threshold()

    def _stale_slot_filling(
        self,
        state: ConversationWorkflowState,
        draft,
        explicit_continue: bool,
    ) -> WorkflowRecoveryAssessment:
        label = (state.slots.get("bill_name") or (draft.bill_name if draft else None) or "expense")
        filled = [k for k, v in state.slots.items() if v and k != "bill_name"]
        detail = f" Saved so far: {', '.join(filled)}." if filled else ""

        if explicit_continue:
            return WorkflowRecoveryAssessment(
                scenario=WorkflowRecoveryScenario.STALE_SLOT_FILLING,
                context={"label": label, "resumed": True},
            )

        return WorkflowRecoveryAssessment(
            scenario=WorkflowRecoveryScenario.STALE_SLOT_FILLING,
            safe_prompt=(
                f"You were adding '{label}' earlier but did not finish.{detail} "
                "Would you like to continue where you left off, or start a new expense?"
            ),
            options=["continue", "new"],
            context={"label": label, "pending_slots": state.pending_slots},
            block_blind_resume=True,
        )

    def _interrupted_submit(
        self,
        ctx: SessionContext,
        state: ConversationWorkflowState,
        draft,
        explicit_continue: bool,
    ) -> WorkflowRecoveryAssessment:
        eid = state.expense_id or (draft.expense_id if draft else None)
        label = state.slots.get("bill_name") or (draft.bill_name if draft else "expense")

        if explicit_continue:
            return WorkflowRecoveryAssessment(
                scenario=WorkflowRecoveryScenario.INTERRUPTED_SUBMIT,
                context={"expense_id": eid},
            )

        return WorkflowRecoveryAssessment(
            scenario=WorkflowRecoveryScenario.INTERRUPTED_SUBMIT,
            safe_prompt=(
                f"Your submit request for '{label}'"
                + (f" (#{eid})" if eid else "")
                + " may not have completed. "
                "I will not submit again without your confirmation. "
                "Would you like to retry submit, continue editing the draft, or cancel?"
            ),
            options=["retry_submit", "edit", "cancel"],
            context={"expense_id": eid, "label": label},
            block_blind_resume=True,
        )
