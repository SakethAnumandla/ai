"""Attach receipt files to an in-chat manual workflow draft without OCR."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.ai.chat_ui import build_workflow_preview_card
from app.ai.conversation.state_machine import ConversationStateMachine, slot_question
from app.ai.schemas.chat_ui import CategoryPickerPayload, ExpensePreviewCard
from app.ai.schemas.workflow import ConversationWorkflowState
from app.ai.workflow.draft_persist import persist_workflow_draft
from app.ai.workflow.manual_slots import build_category_picker, category_ui_actions
from app.models import Expense, User
from app.utils.expense_helpers import attach_files_to_expense

_MANUAL_ATTACHMENT_SLOT = "_awaiting_attachment"


def attach_receipt_to_manual_workflow(
    db: Session,
    user: User,
    workflow_state: ConversationWorkflowState,
    file_infos: List[dict],
) -> Tuple[
    ConversationWorkflowState,
    Optional[ExpensePreviewCard],
    str,
    Optional[CategoryPickerPayload],
    Optional[list],
]:
    """
    Save uploaded files on the existing manual draft expense (no vision scan).
    Returns (updated_state, preview_card, assistant_message, category_picker, ui_actions).
    """
    state, expense_id = persist_workflow_draft(db, user, workflow_state)
    if not expense_id:
        raise ValueError("Complete bill name, amount, vendor, and category before uploading.")

    expense = (
        db.query(Expense)
        .filter(
            Expense.id == expense_id,
            Expense.user_id == user.id,
            Expense.company_id == getattr(user, "company_id", 1),
        )
        .first()
    )
    if not expense:
        raise ValueError("Draft expense not found.")

    for index, file_info in enumerate(file_infos):
        file_info["is_primary"] = index == 0
    attach_files_to_expense(db, expense, file_infos)
    db.commit()

    state.slots.pop(_MANUAL_ATTACHMENT_SLOT, None)
    state.slots["_attachment_complete"] = True
    state.updated_at = datetime.utcnow()

    sm = ConversationStateMachine()
    state.pending_slots = sm._recompute_pending_slots(state.slots)
    next_slot = state.pending_slots[0] if state.pending_slots else None

    preview = build_workflow_preview_card(db, expense_id=int(expense_id), slots=state.slots)
    category_picker = None
    ui_actions = None
    if next_slot:
        message = f"Receipt saved ✅ {slot_question(next_slot, slots=state.slots)}"
        if next_slot in ("main_category", "sub_category", "line_item"):
            category_picker = build_category_picker(next_slot, slots=state.slots)
            ui_actions = category_ui_actions(next_slot, slots=state.slots)
    else:
        message = (
            "Your receipt has been saved. Review the details below, "
            "then tap **Edit** or **Submit for approval**."
        )

    return state, preview, message, category_picker, ui_actions
