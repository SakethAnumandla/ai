"""Persist in-chat manual workflow slots as a DRAFT expense row."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.ai.schemas.workflow import ConversationWorkflowState
from app.ai.tools.handlers.expense_handlers import _parse_category
from app.ai.workflow.manual_slots import normalize_slots_taxonomy
from app.ai.workflow.slot_parser import sanitize_sub_category
from app.ai.tools.expense_create_enrichment import bill_name_needs_repair
from app.models import ExpenseStatus, TransactionType, UploadMethod, User
from app.schemas import ExpenseCreate, ExpenseUpdate
from app.services.expense_service import ExpenseService
from app.services.tax_service import TaxService
from app.utils.category_hashtags import normalize_hashtags_list
from app.utils.date_parser import parse_bill_date
from app.utils.expense_business_fields import apply_business_fields
from app.utils.expense_helpers import parse_payment_method


def _company_id(user: User) -> int:
    return int(getattr(user, "company_id", None) or 1)


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
        "_attachment_complete",
        "selected_categories",
        "extra_category_tags",
    ):
        args.pop(internal, None)

    bill_name = args.pop("bill_name", None)
    if not bill_name or bill_name_needs_repair(str(bill_name)):
        bill_name = args.get("vendor_name") or "expense"

    payment_method = args.pop("payment_method", None)

    sub = sanitize_sub_category(
        args.get("main_category"),
        args.get("sub_category"),
        vendor_name=args.get("vendor_name"),
        bill_name=bill_name,
    )

    normalize_slots_taxonomy(args)

    tool_args: Dict[str, Any] = {
        "bill_name": bill_name,
        "bill_amount": args.get("bill_amount"),
        "vendor_name": args.get("vendor_name"),
        "main_category": args.get("main_category"),
        "sub_category": sub or args.get("sub_category"),
        "line_item": args.get("line_item"),
        "description": args.get("description"),
        "submitted_by_name": args.get("submitted_by_name"),
        "submitted_by_role": args.get("submitted_by_role"),
        "tax_amount": args.get("tax_amount"),
    }
    if payment_method:
        tool_args["payment_method"] = payment_method
    if args.get("bill_date"):
        tool_args["bill_date"] = args.get("bill_date")
    extra_tags = args.get("extra_category_tags") or []
    if extra_tags:
        tool_args["hashtags"] = normalize_hashtags_list(extra_tags)
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
    bill_name = tool_args.get("bill_name")
    if not bill_name or amount is None or float(amount) <= 0:
        return state, state.expense_id or state.slots.get("expense_id")

    svc = ExpenseService(db)
    expense_id = state.expense_id or state.slots.get("expense_id")
    company_id = _company_id(user)

    parsed_date = datetime.utcnow()
    if tool_args.get("bill_date"):
        try:
            parsed_date = parse_bill_date(str(tool_args["bill_date"]))
        except Exception:
            pass

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
        if tool_args.get("line_item"):
            update_fields["line_item"] = tool_args["line_item"]
        if tool_args.get("payment_method"):
            update_fields["payment_method"] = tool_args["payment_method"]
        if tool_args.get("description") is not None:
            update_fields["description"] = tool_args["description"]
        if tool_args.get("submitted_by_name"):
            update_fields["submitted_by_name"] = tool_args["submitted_by_name"]
        if tool_args.get("submitted_by_role"):
            update_fields["submitted_by_role"] = tool_args["submitted_by_role"]
        if tool_args.get("tax_amount") is not None:
            update_fields["tax_amount"] = float(tool_args["tax_amount"])
        update_fields["bill_date"] = parsed_date
        if tool_args.get("hashtags"):
            update_fields["hashtags"] = tool_args["hashtags"]
        if update_fields:
            svc.update_expense(
                int(expense_id),
                user.id,
                ExpenseUpdate(**update_fields),
                company_id=company_id,
            )
        expense = svc.get_expense(int(expense_id), user.id, company_id)
        if expense and tool_args.get("tax_amount") and float(tool_args["tax_amount"]) > 0:
            TaxService(db).import_from_ocr_breakdown(
                expense, None, total_tax=float(tool_args["tax_amount"])
            )
        apply_business_fields(
            expense,
            main_category=update_fields.get("main_category") or expense.main_category,
            sub_category=tool_args.get("sub_category"),
            line_item=tool_args.get("line_item"),
            bill_date=parsed_date,
            vendor_name=tool_args.get("vendor_name"),
        )
        state.expense_id = int(expense_id)
        state.slots["expense_id"] = int(expense_id)
        return state, int(expense_id)

    parsed_main = _parse_category(tool_args.get("main_category"))
    expense_payload = {
        "bill_name": tool_args["bill_name"],
        "bill_amount": float(tool_args["bill_amount"]),
        "bill_date": parsed_date,
        "transaction_type": TransactionType.EXPENSE,
        "main_category": parsed_main,
        "sub_category": tool_args.get("sub_category"),
        "line_item": tool_args.get("line_item"),
        "vendor_name": tool_args.get("vendor_name"),
        "payment_method": parse_payment_method(tool_args.get("payment_method")),
        "description": (tool_args.get("description") or "").strip() or None,
        "submitted_by_name": tool_args.get("submitted_by_name"),
        "submitted_by_role": tool_args.get("submitted_by_role"),
        "tax_amount": float(tool_args.get("tax_amount") or 0.0),
        "hashtags": tool_args.get("hashtags"),
    }
    expense_data = ExpenseCreate(**{k: v for k, v in expense_payload.items() if v is not None})
    expense = svc.create_expense(
        db,
        expense_data,
        user.id,
        UploadMethod.MANUAL,
        status=ExpenseStatus.DRAFT,
        company_id=company_id,
    )
    apply_business_fields(
        expense,
        main_category=parsed_main,
        sub_category=tool_args.get("sub_category"),
        line_item=tool_args.get("line_item"),
        bill_date=parsed_date,
        vendor_name=tool_args.get("vendor_name"),
    )
    if tool_args.get("tax_amount") and float(tool_args["tax_amount"]) > 0:
        TaxService(db).import_from_ocr_breakdown(
            expense, None, total_tax=float(tool_args["tax_amount"])
        )
    state.expense_id = expense.id
    state.slots["expense_id"] = expense.id
    return state, expense.id
