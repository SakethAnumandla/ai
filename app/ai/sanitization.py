"""
Enterprise PII sanitization — never persist raw prompts/responses.

Masks: emails, phone numbers, GSTIN, card numbers, bank account numbers.

Public API:
  sanitize_prompt()   — user/system content before storage
  sanitize_response() — assistant/tool content before storage
"""
import re
from typing import Any, Dict, List, Union

# --- Mask tokens (stable for audit/search) ---
MASK_EMAIL = "[EMAIL_REDACTED]"
MASK_PHONE = "[PHONE_REDACTED]"
MASK_GST = "[GST_REDACTED]"
MASK_CARD = "[CARD_REDACTED]"
MASK_BANK = "[BANK_ACCOUNT_REDACTED]"

# Indian GSTIN: 15 chars — 2 digit state + 10 PAN + entity + Z + checksum
_GSTIN_RE = re.compile(
    r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b",
    re.IGNORECASE,
)

# Email
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
)

# Phone: +91, 0-prefix, 10-digit Indian mobile, generic international
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{4,6}(?!\d)"
    r"|(?<!\d)\+91[-.\s]?\d{10}(?!\d)"
    r"|(?<!\d)0\d{10}(?!\d)"
    r"|(?<!\d)[6-9]\d{9}(?!\d)",
)

# Card numbers: 13–19 digits with optional separators (Visa/MC/Amex lengths)
_CARD_RE = re.compile(
    r"\b(?:\d[ -]*?){13,19}\b",
)

# Bank account: 9–18 consecutive digits not already part of GST/card (applied after card)
_BANK_RE = re.compile(
    r"(?<![A-Z0-9])\b\d{9,18}\b(?![A-Z0-9])",
)


def _mask_cards(text: str) -> str:
    def _repl(match: re.Match) -> str:
        raw = re.sub(r"[\s-]", "", match.group(0))
        if not raw.isdigit():
            return match.group(0)
        if len(raw) < 13 or len(raw) > 19:
            return match.group(0)
        # Luhn-lite: skip if looks like a year or small amount
        if len(raw) <= 10:
            return match.group(0)
        return MASK_CARD

    return _CARD_RE.sub(_repl, text)


def _mask_bank_accounts(text: str) -> str:
    def _repl(match: re.Match) -> str:
        digits = match.group(0)
        if len(digits) < 9:
            return digits
        return MASK_BANK

    return _BANK_RE.sub(_repl, text)


def _sanitize_text(text: str) -> str:
    if not text:
        return text
    out = text
    out = _EMAIL_RE.sub(MASK_EMAIL, out)
    out = _GSTIN_RE.sub(MASK_GST, out)
    out = _PHONE_RE.sub(MASK_PHONE, out)
    out = _mask_cards(out)
    out = _mask_bank_accounts(out)
    return out


def sanitize_prompt(content: Union[str, Dict[str, Any], List[Any]]) -> Union[str, Dict[str, Any], List[Any]]:
    """Sanitize user/system prompts before persistence or audit."""
    if isinstance(content, str):
        return _sanitize_text(content)
    if isinstance(content, dict):
        return {k: sanitize_prompt(v) for k, v in content.items()}
    if isinstance(content, list):
        return [sanitize_prompt(item) for item in content]
    return content


def sanitize_response(content: Union[str, Dict[str, Any], List[Any]]) -> Union[str, Dict[str, Any], List[Any]]:
    """Sanitize assistant/tool responses before persistence or audit."""
    return sanitize_prompt(content)
