"""Detect user confirmation / cancellation in natural language."""
import re

_AFFIRM_RE = re.compile(
    r"^(yes|yeah|yep|confirm|confirmed|go ahead|proceed|do it|submit|submit it|ok|okay|sure|approve)"
    r"(?:\s+please)?\.?$",
    re.IGNORECASE,
)
_DENY_RE = re.compile(
    r"^(no|nope|cancel|stop|don'?t|never mind|abort)\.?$",
    re.IGNORECASE,
)


def is_affirmation(text: str) -> bool:
    return bool(_AFFIRM_RE.match(text.strip()))


def is_submit_confirmation(text: str) -> bool:
    """
    True when the user wants to submit/save the prepared expense.
    Covers short replies (yes) and phrases like 'yes save the bill'.
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if is_affirmation(stripped):
        return True
    from app.ai.vendor_guard import is_draft_confirmation

    if is_draft_confirmation(stripped):
        return True
    lowered = stripped.lower()
    if re.match(
        r"^(yes|yeah|yep|ok|okay|sure|confirm|confirmed|go ahead|proceed|submit|save)",
        lowered,
    ) and re.search(r"\b(save|submit|add|record|log|bill|expense)\b", lowered):
        return True
    return False


def is_denial(text: str) -> bool:
    return bool(_DENY_RE.match(text.strip()))
