"""Detect when the user is describing a new expense (not resuming an old draft)."""
import re

from app.ai.orchestrator.intent import UserIntent


def describes_new_expense(text: str, *, intent=None) -> bool:
    """
    True when the message is clearly about logging/creating a new expense,
    so stale-draft recovery should not block the conversation.
    """
    if intent is not None and getattr(intent, "intent", None) == UserIntent.CREATE_EXPENSE:
        return True

    lowered = text.strip().lower()
    if not lowered:
        return False

    if re.search(r"\bstart\s+(a\s+)?new\s+expense\b", lowered, re.I):
        return True

    create_patterns = (
        r"\b(add|create|new|log|record|save)\b.*\b(expense|bill|receipt)\b",
        r"\bhelp\s+me\s+log\b",
        r"\b(log|record)\s+it\b",
        r"\bhad\s+(lunch|dinner|breakfast|brunch)\b",
        r"\bhad\s+[a-z]+\s+(?:pizza|burger|biryani|meal|coffee)\b",
        r"\bspent\b.*\b(at|for|on)\b",
        r"\bpaid\s+(?:using|via|through|with)\b",
        r"\b(lunch|dinner|meal)\b.*\b(for|at|yesterday|today)\b",
        r"\bwent\s+(?:for|to)\b",
        r"\bbill was\s+\d+",
        r"\b(restaurant|hotel|cab|uber)\b",
        r"\bate\s+\w+.*\bbill\b",
    )
    if not any(re.search(p, lowered, re.I) for p in create_patterns):
        return False

    has_amount = bool(
        re.search(
            r"(?:₹|rs\.?|rupees?)\s*\d+|\d+\s*(?:rupees?|rs\.?|₹)|\bfor\s+\d+|\bbill was\s+\d+",
            lowered,
            re.I,
        )
    )
    has_vendor = bool(
        re.search(r"\b(?:at|in|from)\s+[a-z0-9]", lowered, re.I)
        or re.search(r"\bwhich is\s+[a-z]", lowered, re.I)
        or re.search(
            r"\b(?:hotel|restaurant|cafe|store|shop)\s+name\s+is\s+[a-z]",
            lowered,
            re.I,
        )
        or re.search(
            r"\b(pizzahut|pizza\s*hut|dominos|swiggy|zomato|uber|ola|amazon|kfc|mcdonalds)\b",
            lowered,
            re.I,
        )
    )
    has_meal = bool(re.search(r"\b(lunch|dinner|breakfast|brunch|coffee|cafe)\b", lowered, re.I))
    wants_log = bool(re.search(r"\b(log|record|help me|add|create)\b", lowered, re.I))

    return has_amount or has_vendor or (has_meal and wants_log)
