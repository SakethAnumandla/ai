"""Helpers for expense.search tool — status aliases and chat-friendly listing."""
import re
from typing import List, Optional, Tuple

from app.models import ExpenseStatus

_PENDING_STATUS_ALIASES = frozenset(
    {"pending", "open", "awaiting", "awaiting_approval", "in_progress", "unsubmitted"}
)

_PENDING_BILLS_RE = re.compile(
    r"(?:"
    r"\b(?:show|list|view|get|see|display|all|my)\b.*\b(?:pending|open|awaiting)\b.*\b(?:bill|expense)s?\b"
    r"|\b(?:pending|open|awaiting)\b.*\b(?:bill|expense)s?\b"
    r"|\bpending\s+bills?\b"
    r")",
    re.IGNORECASE,
)


def is_pending_bills_query(text: str) -> bool:
    return bool(_PENDING_BILLS_RE.search((text or "").strip()))


def resolve_expense_search_statuses(
    status: Optional[str],
) -> Tuple[Optional[ExpenseStatus], Optional[List[ExpenseStatus]], bool]:
    """
    Map status string to DB filter.
    Returns (single_status, multi_statuses, is_pending_view).
    """
    if not status or not str(status).strip():
        return None, None, False
    key = str(status).lower().strip()
    if key in _PENDING_STATUS_ALIASES:
        return None, [
            ExpenseStatus.DRAFT,
            ExpenseStatus.SUBMITTED,
            ExpenseStatus.PENDING,
        ], True
    try:
        return ExpenseStatus(key), None, False
    except ValueError:
        return None, None, False


def format_expense_search_message(
    items: list,
    total: int,
    *,
    pending_view: bool = False,
) -> str:
    if not items:
        if pending_view:
            return "You have no pending bills right now — nothing in draft or awaiting approval."
        return "No expenses matched your search."

    header = (
        f"Here are your pending bills ({total} total):"
        if pending_view
        else f"Found {total} expense(s); showing {len(items)}."
    )
    lines = [header, ""]
    for row in items:
        vendor = row.get("vendor_name") or row.get("bill_name") or "Expense"
        amount = row.get("bill_amount") or 0
        st = (row.get("status") or "—").replace("_", " ")
        eid = row.get("expense_id")
        if amount == int(amount):
            amt = f"₹{int(amount):,}"
        else:
            amt = f"₹{amount:,.2f}"
        lines.append(f"• #{eid} {vendor} — {amt} ({st})")
    if total > len(items):
        lines.append("")
        lines.append(f"Showing {len(items)} of {total}. Say “show all pending bills” with a higher limit if you need more.")
    return "\n".join(lines)
