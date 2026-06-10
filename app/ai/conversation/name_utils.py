"""Name extraction from user messages — shared by handler and responses."""
import re
from typing import Optional

_NAME_INTRO = re.compile(
    r"\b(?:my name is|i'?m|i am|call me|this is)\s+([a-z][a-z\s'-]{0,40})",
    re.IGNORECASE,
)


def title_name(raw: str) -> str:
    cleaned = raw.strip().strip(".,!?")
    parts = cleaned.split()
    return " ".join(p[:1].upper() + p[1:].lower() if p else "" for p in parts[:3])


def extract_name_from_text(text: str) -> Optional[str]:
    m = _NAME_INTRO.search(text or "")
    if not m:
        return None
    name = title_name(m.group(1))
    return name if len(name) >= 2 else None


def parse_name_from_message(message: str) -> Optional[str]:
    return extract_name_from_text(message)
