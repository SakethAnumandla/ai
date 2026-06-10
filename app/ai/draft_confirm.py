"""Confirm an existing OCR / session draft without creating a duplicate expense."""
from typing import Any, Dict

from app.ai.schemas.memory import DraftExpenseContext
from app.ai.vendor_guard import is_draft_confirmation, resolve_vendor_from_draft
from app.ai.workflow.slot_parser import is_payment_method_text, sanitize_sub_category

# Re-export for callers that import from draft_confirm
__all__ = ("is_draft_confirmation", "draft_confirm_tool_arguments")


def draft_confirm_tool_arguments(draft: DraftExpenseContext) -> Dict[str, Any]:
    """Build expense.create.v1 args that update the existing draft row."""
    args: Dict[str, Any] = {
        "expense_id": draft.expense_id,
        "save_as_draft": False,
        "bill_name": draft.bill_name or "expense",
    }
    if draft.bill_amount is not None:
        args["bill_amount"] = draft.bill_amount
    if draft.payment_method:
        args["payment_method"] = draft.payment_method
    vendor = resolve_vendor_from_draft(draft)
    if vendor:
        args["vendor_name"] = vendor
    if draft.main_category:
        args["main_category"] = draft.main_category
    if draft.sub_category and not is_payment_method_text(draft.sub_category):
        mapped = sanitize_sub_category(
            draft.main_category or "food",
            draft.sub_category,
            vendor_name=vendor,
            bill_name=draft.bill_name,
        )
        if mapped:
            args["sub_category"] = mapped
    token = (draft.raw_ocr_hints or {}).get("review_token")
    if token:
        args["review_token"] = token
    return args
