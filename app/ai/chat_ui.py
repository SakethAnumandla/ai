"""Build structured chat UI from OCR pipeline results."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session, joinedload

from app.ai.schemas.chat_ui import (
    ChatUIAction,
    ExpenseFieldPreview,
    ExpensePreviewCard,
    build_fields_from_prefill,
    default_expense_card_actions,
)
from app.intelligence.schemas import ReceiptPipelineResult
from app.models import Expense
from app.utils.expense_helpers import build_expense_response


def build_expense_preview_card(
    db: Session,
    result: ReceiptPipelineResult,
) -> Optional[ExpensePreviewCard]:
    if not result.expense_id:
        return None

    expense = (
        db.query(Expense)
        .options(joinedload(Expense.files))
        .filter(Expense.id == result.expense_id)
        .first()
    )
    if not expense:
        return None

    preview_url = None
    thumbnail_url = None
    can_preview = False
    try:
        resp = build_expense_response(expense)
        preview_url = resp.preview_url
        thumbnail_url = resp.thumbnail_url
        can_preview = bool(resp.can_preview)
    except Exception:
        primary = expense.files[0] if expense.files else None
        if primary:
            preview_url = primary.preview_url or primary.file_url
            can_preview = bool(primary.can_preview)

    prefill = dict(result.prefill or {})
    af = result.autofill
    if af.bill_name:
        prefill.setdefault("bill_name", af.bill_name)
    if af.bill_amount is not None:
        prefill.setdefault("bill_amount", af.bill_amount)
    if af.vendor_name:
        prefill.setdefault("vendor_name", af.vendor_name)
    if af.main_category:
        prefill.setdefault("main_category", af.main_category)
    if af.payment_method:
        prefill.setdefault("payment_method", af.payment_method)

    status = expense.status.value if expense.status else "draft"
    clarify = list(af.fields_needing_clarification or [])
    fields = build_fields_from_prefill(prefill)

    return ExpensePreviewCard(
        expense_id=expense.id,
        bill_name=expense.bill_name,
        bill_amount=expense.bill_amount,
        currency_code=expense.currency_code,
        vendor_name=expense.vendor_name,
        main_category=expense.main_category.value if expense.main_category else None,
        sub_category=expense.sub_category,
        payment_method=(
            expense.payment_method.value if expense.payment_method else af.payment_method
        ),
        bill_date=expense.bill_date.isoformat() if expense.bill_date else None,
        status=status,
        preview_url=preview_url,
        thumbnail_url=thumbnail_url,
        can_preview=can_preview,
        overall_confidence=result.overall_confidence,
        fields=fields,
        fields_needing_clarification=clarify,
        actions=default_expense_card_actions(expense.id, status=status),
        is_duplicate=result.is_duplicate,
        has_bill_attachment=bool(expense.files),
    )


def build_expense_preview_cards(
    db: Session,
    results: List[ReceiptPipelineResult],
) -> List[ExpensePreviewCard]:
    cards: List[ExpensePreviewCard] = []
    for result in results:
        card = build_expense_preview_card(db, result)
        if card:
            cards.append(card)
    return cards


def format_preview_message(cards: List[ExpensePreviewCard]) -> str:
    if not cards:
        return (
            "I read your receipt(s). Review the details below and tap **Submit** "
            "when ready, or **Edit** to change any field."
        )
    if len(cards) == 1:
        c = cards[0]
        vendor = c.vendor_name or c.bill_name or "this bill"
        amount = f"{c.bill_amount:,.2f}" if c.bill_amount else "the amount shown"
        return (
            f"I've extracted details from **{vendor}** ({amount}). "
            "Preview your receipt below, review the fields, then **Submit** or **Edit**."
        )
    labels = ", ".join(
        (c.vendor_name or c.bill_name or f"Bill #{c.expense_id}") for c in cards
    )
    return (
        f"I read **{len(cards)} bills** ({labels}). "
        "Each preview is shown below — review, edit if needed, then submit them one by one "
        "or say **submit all**."
    )


def build_workflow_preview_card(
    db: Session,
    *,
    expense_id: int,
    slots: dict,
) -> Optional[ExpensePreviewCard]:
    """Preview card for manual chatbot workflow after draft is persisted."""
    q = (
        db.query(Expense)
        .options(joinedload(Expense.files))
        .filter(Expense.id == expense_id)
    )
    if slots.get("user_id") is not None:
        q = q.filter(Expense.user_id == int(slots["user_id"]))
    if slots.get("company_id") is not None:
        q = q.filter(Expense.company_id == int(slots["company_id"]))
    expense = q.first()
    if not expense:
        return None

    resp = build_expense_response(expense)
    prefill = {
        "bill_name": expense.bill_name,
        "bill_amount": expense.bill_amount,
        "vendor_name": expense.vendor_name or slots.get("vendor_name"),
        "main_category": (
            expense.main_category.value if expense.main_category else slots.get("main_category")
        ),
        "sub_category": expense.sub_category or slots.get("sub_category"),
        "line_item": expense.line_item or slots.get("line_item"),
        "tax_amount": expense.tax_amount if expense.tax_amount else slots.get("tax_amount"),
        "submitted_by_name": expense.submitted_by_name or slots.get("submitted_by_name"),
        "submitted_by_role": expense.submitted_by_role or slots.get("submitted_by_role"),
        "payment_method": (
            expense.payment_method.value if expense.payment_method else slots.get("payment_method")
        ),
        "description": expense.description or slots.get("description"),
        "bill_date": expense.bill_date,
        "bill_number": expense.bill_number,
    }
    fields = build_fields_from_prefill(prefill)
    has_bill = bool(expense.files)
    fields.append(
        ExpenseFieldPreview(
            key="bill_attachment",
            label="Bill attached",
            value="Yes" if has_bill else "No",
        )
    )
    status = expense.status.value if expense.status else "draft"
    return ExpensePreviewCard(
        expense_id=expense.id,
        bill_name=expense.bill_name,
        bill_amount=expense.bill_amount,
        currency_code=expense.currency_code,
        vendor_name=expense.vendor_name,
        main_category=expense.main_category.value if expense.main_category else None,
        sub_category=expense.sub_category,
        payment_method=(
            expense.payment_method.value if expense.payment_method else None
        ),
        bill_date=expense.bill_date.isoformat() if expense.bill_date else None,
        status=status,
        preview_url=resp.preview_url if has_bill else None,
        thumbnail_url=resp.thumbnail_url if has_bill else None,
        can_preview=bool(resp.can_preview) if has_bill else False,
        fields=fields,
        actions=default_expense_card_actions(expense.id, status=status),
        has_bill_attachment=has_bill,
    )
