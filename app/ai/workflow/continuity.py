"""Resume interrupted expense drafts and workflows across sessions."""
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.conversation.state_machine import ConversationStateMachine
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.schemas.memory import DraftExpenseContext
from app.ai.schemas.memory_intelligence import WorkflowRecoveryAssessment, WorkflowRecoveryScenario
from app.ai.schemas.workflow import ContinuityResult, WorkflowScope, WorkflowType
from app.ai.services.memory_service import MemoryService
from app.models import Expense, ExpenseStatus

_CONTINUE_RE = re.compile(
    r"\b(continue|resume|finish|complete)\b.*\b(expense|draft|claim|submission)?\b",
    re.I,
)


class WorkflowContinuityService:
    """Detect continue intents and rebuild conversational workflow state."""

    def __init__(self, db: Session, memory: MemoryService):
        self._db = db
        self._memory = memory
        self._state_machine = ConversationStateMachine()

    def is_continue_intent(self, text: str) -> bool:
        return bool(_CONTINUE_RE.search(text.strip()))

    def _latest_db_draft(self, user_id: int) -> Optional[Expense]:
        return (
            self._db.query(Expense)
            .filter(
                Expense.user_id == user_id,
                Expense.status.in_((ExpenseStatus.DRAFT, ExpenseStatus.REJECTED)),
            )
            .order_by(Expense.updated_at.desc(), Expense.created_at.desc())
            .first()
        )

    async def try_resume(
        self,
        ctx: SessionContext,
        text: str,
        *,
        recovery: Optional[WorkflowRecoveryAssessment] = None,
    ) -> ContinuityResult:
        if not self.is_continue_intent(text):
            return ContinuityResult(handled=False)

        if recovery and recovery.block_blind_resume and recovery.safe_prompt:
            if recovery.scenario == WorkflowRecoveryScenario.EXPIRED_CONFIRMATION:
                return ContinuityResult(
                    handled=True,
                    message=recovery.safe_prompt,
                )
            if recovery.scenario in (
                WorkflowRecoveryScenario.INTERRUPTED_SUBMIT,
                WorkflowRecoveryScenario.STALE_SLOT_FILLING,
                WorkflowRecoveryScenario.AMBIGUOUS_DRAFT,
            ):
                return ContinuityResult(
                    handled=True,
                    message=(
                        f"{recovery.safe_prompt} "
                        "Reply 'continue' to resume the previous workflow, or describe a new request."
                    ),
                )

        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        redis_draft = await self._memory.get_draft_expense(ctx)
        db_draft = self._latest_db_draft(ctx.user_id)

        draft_ctx: Optional[DraftExpenseContext] = redis_draft
        if db_draft and (not draft_ctx or not draft_ctx.expense_id):
            draft_ctx = DraftExpenseContext(
                expense_id=db_draft.id,
                bill_name=db_draft.bill_name,
                bill_amount=db_draft.bill_amount,
                vendor_name=db_draft.vendor_name,
                main_category=db_draft.main_category.value if db_draft.main_category else None,
                sub_category=db_draft.sub_category,
                fields_pending=[],
            )

        if not draft_ctx:
            return ContinuityResult(
                handled=True,
                message="I don't see an incomplete expense draft. Would you like to create a new expense?",
            )

        state = self._state_machine.start_from_draft(draft_ctx, session_id=ctx.session_id)
        state.session_id = ctx.session_id
        await self._memory.set_workflow_state(ctx, state)
        await self._memory.set_draft_expense(ctx, self._state_machine.state_to_draft(state))

        pending = state.pending_slots
        if pending:
            from app.ai.conversation.state_machine import _SLOT_QUESTIONS
            first = pending[0]
            label = draft_ctx.bill_name or "your expense"
            msg = (
                f"Continuing {label}"
                + (f" (₹{draft_ctx.bill_amount:,.0f})" if draft_ctx.bill_amount else "")
                + f". {_SLOT_QUESTIONS.get(first, 'What detail should we add next?')}"
            )
        else:
            msg = (
                f"Your draft '{draft_ctx.bill_name}' is ready. "
                "Would you like me to submit it for approval?"
            )

        return ContinuityResult(handled=True, message=msg, resumed_state=state)
