"""Post-expense-save follow-up turn (anything else? / thank you)."""
import re

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
