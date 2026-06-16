"""Structured chat UI payloads (preview cards, actions) for expense copilot."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatUIAction(BaseModel):
    """Client-renderable action (button) in the chat thread."""

    action: str = Field(
        ...,
        description="submit | edit | delete | attach | skip | view_expense | select_category",
    )
    label: str
    expense_id: Optional[int] = None
    fields: List[str] = Field(default_factory=list)
    style: str = Field(default="secondary", description="primary | secondary | danger")


class CategoryOption(BaseModel):
    value: str
    label: str
    icon: Optional[str] = None


class CategoryPickerPayload(BaseModel):
    """Category hierarchy for chat manual expense (same data as GET /categories/manual)."""

    step: str = Field(description="main | sub | line_item")
    multi_select: bool = False
    main_categories: List[CategoryOption] = Field(default_factory=list)
    options: List[CategoryOption] = Field(default_factory=list)
    selected: List[str] = Field(default_factory=list)
    parent_main: Optional[str] = None
    parent_sub: Optional[str] = None
    hierarchy: Optional[Dict[str, Any]] = None


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
    currency_code: Optional[str] = None
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
    has_bill_attachment: bool = False


def _submit_action_label() -> str:
    from app.config import settings

    if settings.expense_self_auto_approve_enabled:
        return "Save expense"
    return "Submit for approval"


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
            label=_submit_action_label(),
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


def workflow_summary_actions(expense_id: Optional[int] = None) -> List[ChatUIAction]:
    """Edit / Submit buttons shown after manual slot collection (upload is a separate step)."""
    if expense_id:
        return default_expense_card_actions(expense_id, status="draft")
    return [
        ChatUIAction(action="edit", label="Edit", style="secondary"),
        ChatUIAction(action="submit", label=_submit_action_label(), style="primary"),
    ]


def ocr_upload_actions() -> List[ChatUIAction]:
    """Single upload button for OCR / receipt-scan creation mode."""
    return [
        ChatUIAction(action="attach", label="Upload receipt", style="primary"),
    ]


def attachment_prompt_actions() -> List[ChatUIAction]:
    return [
        ChatUIAction(action="attach", label="Upload bill", style="primary"),
        ChatUIAction(action="skip", label="Skip", style="secondary"),
    ]


def edit_field_actions() -> List[ChatUIAction]:
    fields = [
        ("bill_name", "Bill name"),
        ("vendor_name", "Vendor"),
        ("bill_amount", "Amount"),
        ("main_category", "Category"),
        ("sub_category", "Sub-category"),
        ("line_item", "Line item"),
        ("tax_amount", "Tax"),
        ("submitted_by_name", "Submitted by"),
        ("submitted_by_role", "Role"),
        ("bill_date", "Bill date"),
        ("description", "Description"),
    ]
    return [
        ChatUIAction(action="edit", label=label, fields=[key], style="secondary")
        for key, label in fields
    ]


def post_submit_actions(expense_id: int) -> List[ChatUIAction]:
    return [
        ChatUIAction(
            action="view_expense",
            label="View expense",
            expense_id=expense_id,
            style="primary",
        ),
    ]


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
        ("line_item", "line_item", "Line item"),
        ("tax_amount", "tax_amount", "Tax"),
        ("submitted_by_name", "submitted_by_name", "Submitted by"),
        ("submitted_by_role", "submitted_by_role", "Role"),
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
            display = f"{float(val):,.2f}" if val else None
        elif key == "tax_amount":
            display = f"{float(val):,.2f}" if val is not None else None
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
