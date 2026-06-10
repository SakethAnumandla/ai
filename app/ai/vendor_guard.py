"""Reject chat commands mistaken for merchant / vendor names."""
import re
from typing import Any, Dict, Optional

from app.ai.schemas.memory import DraftExpenseContext

_CONFIRM_RE = re.compile(
    r"\b("
    r"confirm(?:\s+the)?\s+details?|"
    r"confirm(?:\s+this|\s+it|\s+them)?|"
    r"looks?\s+good|"
    r"that'?s?\s+correct|"
    r"save(?:\s+the)?\s+(?:expense|bill|draft)?|"
    r"finalize|"
    r"go\s+ahead\s+and\s+save"
    r")\b",
    re.IGNORECASE,
)


def is_draft_confirmation(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in {
        "yes", "yeah", "yep", "confirm", "confirmed", "ok", "okay", "sure", "proceed", "go ahead",
    }:
        return True
    return bool(_CONFIRM_RE.search(stripped))

_CHAT_VENDOR_BLOCKLIST = frozenset({
    "chat",
    "yes",
    "no",
    "ok",
    "okay",
    "confirm",
    "confirmed",
    "save",
    "submit",
    "bill",
    "expense",
    "draft",
    "details",
    "help",
    "thanks",
    "hello",
    "hi",
    "hey",
    "please",
    "proceed",
    "sure",
})

_COMMAND_IN_TEXT = re.compile(
    r"\b("
    r"save(?:\s+the)?\s+(?:bill|expense|draft)|"
    r"confirm(?:\s+the)?\s+details?|"
    r"submit(?:\s+for)?\s+approval|"
    r"upload(?:ed)?|attach(?:ed)?|"
    r"screenshot|receipt|ocr|scan(?:ned)?"
    r")\b",
    re.IGNORECASE,
)

_EXPLICIT_VENDOR = re.compile(
    r"\b(?:merchant|vendor|restaurant|store|hotel|shop|cafe)\s+(?:name\s+)?(?:is|as|was|=|:)\s+",
    re.IGNORECASE,
)

_FILENAME_BILL = re.compile(r"^bill\s+\d+\s*[—–-]", re.IGNORECASE)


def looks_like_chat_command(text: Optional[str]) -> bool:
    """True when text is a user command, not a merchant name."""
    if not text or not str(text).strip():
        return True
    stripped = str(text).strip()
    if is_draft_confirmation(stripped):
        return True
    lowered = stripped.lower()
    if lowered in _CHAT_VENDOR_BLOCKLIST:
        return True
    if _FILENAME_BILL.match(stripped):
        return True
    if "screenshot" in lowered and re.search(r"\d{4}-\d{2}-\d{2}", lowered):
        return True
    if len(stripped.split()) > 5 and not _EXPLICIT_VENDOR.search(stripped):
        return True
    if _COMMAND_IN_TEXT.search(stripped) and not _EXPLICIT_VENDOR.search(stripped):
        return True
    return False


def sanitize_vendor_name(value: Optional[str]) -> Optional[str]:
    """Return vendor only if it does not look like chat / filename noise."""
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or looks_like_chat_command(cleaned):
        return None
    return cleaned


def merchant_from_entities(entities: Dict[str, Any]) -> Optional[str]:
    if not entities:
        return None
    return sanitize_vendor_name(entities.get("merchant"))


def resolve_vendor_from_draft(draft: DraftExpenseContext) -> Optional[str]:
    """Best merchant for a receipt draft: memory → OCR entities → prefill."""
    trusted = sanitize_vendor_name(draft.vendor_name)
    if trusted:
        return trusted
    hints = draft.raw_ocr_hints or {}
    from_entities = merchant_from_entities(hints.get("entities") or {})
    if from_entities:
        return from_entities
    prefill = hints.get("prefill") or {}
    return sanitize_vendor_name(prefill.get("vendor_name"))
