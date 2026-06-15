"""Persist in-chat manual workflow slots as a DRAFT expense row."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.ai.schemas.workflow import ConversationWorkflowState
from app.ai.tools.handlers.expense_handlers import _parse_category
from app.ai.workflow.slot_parser import sanitize_sub_category
from app.ai.tools.expense_create_enrichment import bill_name_needs_repair
from app.models import ExpenseStatus, TransactionType, UploadMethod, User
from app.schemas import ExpenseCreate, ExpenseUpdate
from app.services.expense_service import ExpenseService
from app.utils.expense_helpers import parse_payment_method


def _build_tool_args(slots: Dict[str, Any]) -> Dict[str, Any]:
    args = dict(slots)
    for internal in (
        "_awaiting_submit_confirm",
        "_awaiting_creation_mode",
        "_awaiting_attachment",
        "_awaiting_edit_field",
        "_edit_target_field",
        "_multi_bill_queue",
        "_source_utterance",
        "creation_mode",
        "expense_id",
    ):
        args.pop(internal, None)

    bill_name = args.pop("bill_name", "expense")
    payment_method = args.pop("payment_method", None)
    if bill_name_needs_repair(bill_name) and args.get("vendor_name"):
        bill_name = str(args["vendor_name"])

    sub = sanitize_sub_category(
        args.get("main_category"),
        args.get("sub_category"),
        vendor_name=args.get("vendor_name"),
        bill_name=bill_name,
    )

    tool_args: Dict[str, Any] = {
        "bill_name": bill_name,
        "bill_amount": args.get("bill_amount"),
        "vendor_name": args.get("vendor_name"),
        "main_category": args.get("main_category"),
    }
    if payment_method:
        tool_args["payment_method"] = payment_method
    if sub:
        tool_args["sub_category"] = sub
    if args.get("description"):
        tool_args["description"] = args["description"]
    return {k: v for k, v in tool_args.items() if v is not None}


def persist_workflow_draft(
    db: Session,
    user: User,
    state: ConversationWorkflowState,
) -> Tuple[ConversationWorkflowState, Optional[int]]:
    """
    Create or update a DRAFT expense from workflow slots.
    Returns (updated_state, expense_id).
    """
    tool_args = _build_tool_args(state.slots)
    amount = tool_args.get("bill_amount")
    if amount is None or float(amount) <= 0:
        return state, state.expense_id or state.slots.get("expense_id")

    svc = ExpenseService(db)
    expense_id = state.expense_id or state.slots.get("expense_id")

    if expense_id:
        update_fields: Dict[str, Any] = {}
        if tool_args.get("bill_name"):
            update_fields["bill_name"] = tool_args["bill_name"]
        if tool_args.get("bill_amount") is not None:
            update_fields["bill_amount"] = float(tool_args["bill_amount"])
        if tool_args.get("vendor_name"):
            update_fields["vendor_name"] = tool_args["vendor_name"]
        if tool_args.get("main_category"):
            update_fields["main_category"] = _parse_category(tool_args["main_category"])
        if tool_args.get("sub_category"):
            update_fields["sub_category"] = tool_args["sub_category"]
        if tool_args.get("payment_method"):
            update_fields["payment_method"] = tool_args["payment_method"]
        if tool_args.get("description") is not None:
            update_fields["description"] = tool_args["description"]
        if update_fields:
            svc.update_expense(int(expense_id), user.id, ExpenseUpdate(**update_fields))
        state.expense_id = int(expense_id)
        state.slots["expense_id"] = int(expense_id)
        return state, int(expense_id)

    parsed_main = _parse_category(tool_args.get("main_category"))
    expense_payload = {
        "bill_name": tool_args["bill_name"],
        "bill_amount": float(tool_args["bill_amount"]),
        "bill_date": datetime.utcnow(),
        "transaction_type": TransactionType.EXPENSE,
        "main_category": parsed_main,
        "sub_category": tool_args.get("sub_category"),
        "vendor_name": tool_args.get("vendor_name"),
        "payment_method": parse_payment_method(tool_args.get("payment_method")),
        "description": (tool_args.get("description") or "").strip() or None,
    }
    expense_data = ExpenseCreate(**{k: v for k, v in expense_payload.items() if v is not None})
    expense = svc.create_expense(
        db, expense_data, user.id, UploadMethod.MANUAL, status=ExpenseStatus.DRAFT
    )
    state.expense_id = expense.id
    state.slots["expense_id"] = expense.id
    return state, expense.id
