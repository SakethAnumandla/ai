"""Post-expense-save follow-up turn (anything else? / thank you)."""
import re

from app.models import ExpenseStatus

BILL_SAVED_AND_APPROVED = "Bill saved and approved."
POST_SAVE_THANK_YOU = "Thank you! Have a great day. 👋"


def saved_expense_message(status: ExpenseStatus) -> str:
    if status == ExpenseStatus.APPROVED:
        return BILL_SAVED_AND_APPROVED
    if status == ExpenseStatus.SUBMITTED:
        return "Expense submitted for approval."
    return BILL_SAVED_AND_APPROVED


def normalize_chat_action(action: str) -> str:
    normalized = (action or "").strip().lower().replace("_", " ")
    if normalized in {"submit", "save", "save expense"}:
        return "submit"
    return (action or "").strip().lower()

_DECLINE_RE = re.compile(
    r"^(no|nope|nah|nothing(?:\s+else)?|none|that'?s?\s+all|all\s+good|i'?m\s+good|not\s+now|no\s+thanks?)\.?$",
    re.IGNORECASE,
)
_ACCEPT_RE = re.compile(
    r"^(yes|yeah|yep|sure|ok|okay|please|yup)\.?$",
    re.IGNORECASE,
)


def is_post_save_decline(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    return bool(_DECLINE_RE.match(stripped))


def is_post_save_accept(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    return bool(_ACCEPT_RE.match(stripped))
