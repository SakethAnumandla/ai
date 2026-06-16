"""Human-readable expense draft summaries for workflow turns."""
from typing import Any, Dict, Optional


def format_amount(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    if amount == int(amount):
        return f"{int(amount):,}"
    return f"{amount:,.2f}"


def _format_payment(method: Optional[str]) -> str:
    if not method:
        return "—"
    if method.lower() == "upi":
        return "UPI"
    return method.replace("_", " ").title()


def _label(value: Optional[str]) -> str:
    if not value:
        return "—"
    return str(value).replace("_", " ").title()


def format_draft_summary(slots: Dict[str, Any], *, intro: str = "Perfect 👍") -> str:
    bill_name = slots.get("bill_name") or "—"
    merchant = slots.get("vendor_name") or "—"
    description = slots.get("description") or "—"
    amount = format_amount(slots.get("bill_amount"))
    category = _label(slots.get("main_category"))
    sub = _label(slots.get("sub_category_raw") or slots.get("sub_category"))
    line_item = _label(slots.get("line_item"))
    tax = format_amount(slots.get("tax_amount"))
    bill_date = slots.get("bill_date") or "—"
    submitter = slots.get("submitted_by_name") or "—"
    role = slots.get("submitted_by_role") or "—"
    extra_cats = slots.get("selected_categories") or []
    if len(extra_cats) > 1:
        category = ", ".join(_label(c) for c in extra_cats)

    lines = [
        f"{intro}",
        "",
        "Expense details:",
        "",
        f"• Bill name: {bill_name}",
        f"• Vendor: {merchant}",
        f"• Amount: {amount}",
        f"• Category: {category}",
    ]
    if sub and sub != "—":
        lines.append(f"• Sub-category: {sub}")
    if line_item and line_item != "—":
        lines.append(f"• Line item: {line_item}")
    lines.extend(
        [
            f"• Tax: {tax}",
            f"• Bill date: {bill_date}",
            f"• Submitted by: {submitter}",
            f"• Role: {role}",
            f"• Description: {description}",
            "",
            "Review the details above. Tap **Edit** to change a field or **Submit** to send for approval.",
        ]
    )
    return "\n".join(lines)
