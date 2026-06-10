"""Human-readable expense draft summaries for workflow turns."""
from typing import Any, Dict, Optional


def format_inr(amount: Optional[float]) -> str:
    if amount is None:
        return "—"
    if amount == int(amount):
        return f"₹{int(amount):,}"
    return f"₹{amount:,.2f}"


def _format_payment(method: Optional[str]) -> str:
    if not method:
        return "—"
    if method.lower() == "upi":
        return "UPI"
    return method.replace("_", " ").title()


def format_draft_summary(slots: Dict[str, Any], *, intro: str = "Perfect 👍") -> str:
    merchant = slots.get("vendor_name") or "—"
    description = slots.get("description") or slots.get("bill_name") or "—"
    amount = format_inr(slots.get("bill_amount"))
    category = (slots.get("main_category") or "—").replace("_", " ").title()
    payment = _format_payment(slots.get("payment_method"))
    sub = slots.get("sub_category_raw") or slots.get("sub_category")
    lines = [
        f"{intro}",
        "",
        "Expense details:",
        "",
        f"• Vendor: {merchant}",
        f"• Description: {description}",
        f"• Amount: {amount}",
        f"• Category: {category}",
        f"• Payment Method: {payment}",
    ]
    if sub:
        if isinstance(sub, str):
            sub = sub.replace("_", " ").title()
        lines.append(f"• Sub Category: {sub}")
    lines.extend(
        [
            "",
            "Would you like me to submit this expense for approval?",
            "",
            "Reply **yes** to submit, or **no** to cancel.",
        ]
    )
    return "\n".join(lines)
