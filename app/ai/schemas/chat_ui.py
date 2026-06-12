"""Structured chat UI payloads (preview cards, actions) for expense copilot."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatUIAction(BaseModel):
    """Client-renderable action (button) in the chat thread."""

    action: str = Field(..., description="submit | edit | delete | attach | skip")
    label: str
    expense_id: Optional[int] = None
    fields: List[str] = Field(default_factory=list)
    style: str = Field(default="secondary", description="primary | secondary | danger")


class ExpenseFieldPreview(BaseModel):
    key: str
    label: str
    value: Optional[str] = None
    needs_review: bool = False


class ExpensePreviewCard(BaseModel):
    """Receipt preview + extracted fields shown below the upload in chat."""

    expense_id: int
    bill_name: Optional[str] = None
    bill_amount: Optional[float] = None
    currency_code: str = "EUR"
    vendor_name: Optional[str] = None
    main_category: Optional[str] = None
    sub_category: Optional[str] = None
    payment_method: Optional[str] = None
    bill_date: Optional[str] = None
    status: str = "draft"
    preview_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    can_preview: bool = False
    overall_confidence: Optional[float] = None
    fields: List[ExpenseFieldPreview] = Field(default_factory=list)
    fields_needing_clarification: List[str] = Field(default_factory=list)
    actions: List[ChatUIAction] = Field(default_factory=list)
    is_duplicate: bool = False


def default_expense_card_actions(expense_id: int, *, status: str) -> List[ChatUIAction]:
    actions = [
        ChatUIAction(
            action="edit",
            label="Edit",
            expense_id=expense_id,
            style="secondary",
        ),
        ChatUIAction(
            action="submit",
            label="Submit for approval",
            expense_id=expense_id,
            style="primary",
        ),
    ]
    if status in ("draft", "rejected"):
        actions.append(
            ChatUIAction(
                action="delete",
                label="Delete",
                expense_id=expense_id,
                style="danger",
            )
        )
    return actions


def format_field_label(key: str) -> str:
    return key.replace("_", " ").strip().title()


def build_fields_from_prefill(prefill: Dict[str, Any]) -> List[ExpenseFieldPreview]:
    mapping = [
        ("vendor_name", "vendor_name", "Merchant"),
        ("bill_name", "bill_name", "Bill name"),
        ("bill_amount", "bill_amount", "Amount"),
        ("bill_date", "bill_date", "Date"),
        ("main_category", "main_category", "Category"),
        ("sub_category", "sub_category", "Sub-category"),
        ("payment_method", "payment_method", "Payment"),
        ("bill_number", "bill_number", "Bill number"),
        ("description", "description", "Description"),
    ]
    fields: List[ExpenseFieldPreview] = []
    for key, src, label in mapping:
        val = prefill.get(src)
        if val is None or val == "":
            continue
        if key == "bill_amount":
            display = f"₹{float(val):,.2f}" if val else None
        elif key in ("bill_date",) and hasattr(val, "isoformat"):
            display = val.isoformat()
        else:
            display = str(val).replace("_", " ").title() if key.endswith("category") else str(val)
        fields.append(
            ExpenseFieldPreview(
                key=key,
                label=label,
                value=display,
                needs_review=bool(prefill.get("amount_needs_review") and key == "bill_amount"),
            )
        )
    return fields
