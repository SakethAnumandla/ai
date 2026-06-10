"""Workflow memory — pending approvals, drafts, incomplete submissions."""
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.confirmation.service import ConfirmationService
from app.ai.schemas.common import SessionContext
from app.ai.schemas.workflow import WorkflowScope, WorkflowSnapshot
from app.models import Expense, ExpenseStatus


class WorkflowSnapshotService:
    def __init__(self, db: Session, confirmation: Optional[ConfirmationService] = None):
        self._db = db
        self._confirmation = confirmation

    def build(
        self,
        ctx: SessionContext,
        *,
        scope: WorkflowScope = WorkflowScope.GENERAL,
    ) -> WorkflowSnapshot:
        drafts = (
            self._db.query(Expense)
            .filter(Expense.user_id == ctx.user_id, Expense.status == ExpenseStatus.DRAFT)
            .order_by(Expense.updated_at.desc())
            .limit(5)
            .all()
        )
        pending_submit = (
            self._db.query(Expense)
            .filter(
                Expense.user_id == ctx.user_id,
                Expense.status.in_(
                    [ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING]
                ),
            )
            .count()
        )

        snap = WorkflowSnapshot(
            draft_count=len(drafts),
            pending_approval_count=pending_submit,
            scope=scope,
        )
        if drafts:
            d = drafts[0]
            snap.latest_draft_id = d.id
            snap.latest_draft_label = d.bill_name
            missing = []
            if not d.bill_amount:
                missing.append("amount")
            if not d.vendor_name:
                missing.append("vendor")
            snap.incomplete_fields = missing

        lines = []
        if drafts:
            lines.append(f"{len(drafts)} draft expense(s) in progress.")
            if snap.latest_draft_label:
                lines.append(f"Latest draft: '{snap.latest_draft_label}' (#{snap.latest_draft_id}).")
        if pending_submit:
            lines.append(f"{pending_submit} expense(s) pending approval.")
        if self._confirmation:
            pending = self._confirmation.get_latest_pending_for_session(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                session_id=ctx.session_id,
            )
            if pending:
                lines.append(f"Awaiting confirmation: {pending.tool_name}.")
        snap.summary_lines = lines
        return snap
