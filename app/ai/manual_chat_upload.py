"""Attach receipt files to an in-chat manual workflow draft without OCR."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.ai.chat_ui import build_workflow_preview_card
from app.ai.schemas.chat_ui import ExpensePreviewCard, default_expense_card_actions
from app.ai.schemas.workflow import ConversationWorkflowState
from app.ai.workflow.draft_persist import persist_workflow_draft
from app.models import Expense, User
from app.utils.expense_helpers import attach_files_to_expense

_MANUAL_ATTACHMENT_SLOT = "_awaiting_attachment"
_SUBMIT_CONFIRM_SLOT = "_awaiting_submit_confirm"


def attach_receipt_to_manual_workflow(
    db: Session,
    user: User,
    workflow_state: ConversationWorkflowState,
    file_infos: List[dict],
) -> Tuple[ConversationWorkflowState, Optional[ExpensePreviewCard], str]:
    """
    Save uploaded files on the existing manual draft expense (no vision scan).
    Returns (updated_state, preview_card, assistant_message).
    """
    state, expense_id = persist_workflow_draft(db, user, workflow_state)
    if not expense_id:
        raise ValueError("Complete expense details before uploading a receipt.")

    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.user_id == user.id)
        .first()
    )
    if not expense:
        raise ValueError("Draft expense not found.")

    for index, file_info in enumerate(file_infos):
        file_info["is_primary"] = index == 0
    attach_files_to_expense(db, expense, file_infos)
    db.commit()

    state.slots.pop(_MANUAL_ATTACHMENT_SLOT, None)
    state.slots[_SUBMIT_CONFIRM_SLOT] = True
    state.updated_at = datetime.utcnow()

    preview = build_workflow_preview_card(db, expense_id=int(expense_id), slots=state.slots)
    if preview:
        preview.actions = default_expense_card_actions(int(expense_id), status=preview.status)

    message = (
        "Your receipt has been saved. Review the expense details below, "
        "then tap **Edit** to change anything or **Submit for approval** when ready."
    )
    return state, preview, message
