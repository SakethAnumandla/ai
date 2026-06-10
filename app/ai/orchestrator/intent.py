"""Lightweight intent detection before tool planning."""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Set


class ConversationIntentType(str, Enum):
    """Social / small-talk intents handled without LLM or tools."""

    SMALL_TALK = "small_talk"
    GREETING = "greeting"
    GRATITUDE = "gratitude"
    QUESTION = "question"
    HOW_ARE_YOU = "how_are_you"
    NAME_INTRO = "name_intro"
    POSITIVE_REPLY = "positive_reply"
    NONE = "none"


_GREETINGS: Set[str] = {
    "hello",
    "hi",
    "hey",
    "hiya",
    "good morning",
    "good afternoon",
    "good evening",
    "morning",
    "evening",
}

_GRATITUDE: Set[str] = {
    "thanks",
    "thank you",
    "thx",
    "ty",
    "thankyou",
}

_POSITIVE_REPLIES: Set[str] = {
    "good",
    "great",
    "fine",
    "nice",
    "not bad",
    "ok",
    "okay",
    "well",
    "pretty good",
    "doing well",
    "doing good",
}

_HOW_ARE_YOU = re.compile(
    r"\bhow\s+(?:are|r)\s+you\b|\bhow\s+do\s+you\s+do\b",
    re.IGNORECASE,
)
_NAME_INTRO = re.compile(
    r"\b(?:my name is|i'?m|i am|call me|this is)\s+([a-z][a-z\s'-]{0,40})",
    re.IGNORECASE,
)
_WHAT_CAN_YOU_DO = re.compile(
    r"\bwhat can you do\b|\bwhat do you do\b|\bhow can you help\b",
    re.IGNORECASE,
)
_CASUAL_CHECKIN = re.compile(
    r"\bwhat'?s up\b|\bhow(?:'s| is) it going\b|\bhow have you been\b",
    re.IGNORECASE,
)


def _normalize_message(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


class UserIntent(str, Enum):
    CREATE_EXPENSE = "create_expense"
    SUBMIT_EXPENSE = "submit_expense"
    DELETE_EXPENSE = "delete_expense"
    UPDATE_EXPENSE = "update_expense"
    SEARCH_EXPENSE = "search_expense"
    APPROVE = "approve"
    LIST_PENDING = "list_pending"
    ANALYTICS = "analytics"
    GENERAL_CHAT = "general_chat"
    CONTINUE_WORKFLOW = "continue_workflow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass
class IntentResult:
    intent: UserIntent
    confidence: float
    hints: dict


_PATTERNS = [
    (UserIntent.CONFIRM, r"^(yes|yeah|confirm|proceed|ok)\.?$", 0.95),
    (UserIntent.CONFIRM, r"\bconfirm(?:\s+the)?\s+details?\b", 0.92),
    (UserIntent.CONFIRM, r"\b(looks?\s+good|that'?s?\s+correct)\b", 0.88),
    (UserIntent.DENY, r"^(no|cancel|stop)\.?$", 0.95),
    (UserIntent.CONTINUE_WORKFLOW, r"\b(continue|resume|finish)\b.*\b(expense|draft)\b", 0.9),
    (UserIntent.CREATE_EXPENSE, r"\b(add|create|new|log)\b.*\b(expense|bill|receipt)\b", 0.85),
    (UserIntent.CREATE_EXPENSE, r"\bhelp\s+me\s+log\b", 0.88),
    (UserIntent.CREATE_EXPENSE, r"\b(log|record)\s+it\b", 0.85),
    (UserIntent.CREATE_EXPENSE, r"\bhad\s+(lunch|dinner|breakfast|brunch)\b", 0.82),
    (UserIntent.SUBMIT_EXPENSE, r"\b(submit|send)\b.*\b(expense|claim|uber|draft)\b", 0.85),
    (UserIntent.DELETE_EXPENSE, r"\b(delete|remove)\b.*\b(expense|expenses|bill|bills|draft)\b", 0.88),
    (UserIntent.DELETE_EXPENSE, r"\bdelete\s+(?:an?\s+)?expense\b", 0.9),
    (UserIntent.UPDATE_EXPENSE, r"\b(update|edit|change|modify)\b.*\b(expense|expenses|bill|bills)\b", 0.88),
    (UserIntent.UPDATE_EXPENSE, r"\b(?:update|edit)\s+(?:an?\s+)?expense\b", 0.9),
    (UserIntent.UPDATE_EXPENSE, r"\b(want|wanted|need|like)\s+to\s+(?:update|edit)\b.*\b(expense|bill)\b", 0.9),
    (UserIntent.SEARCH_EXPENSE, r"\b(find|search|show|list|view|all)\b.*\b(expense|bills?)\b", 0.8),
    (UserIntent.LIST_PENDING, r"\b(pending|open|awaiting)\b.*\b(bill|expense|approval)s?\b", 0.85),
    (UserIntent.APPROVE, r"\b(approve|reject)\b.*\b(claim|expense|travel)\b", 0.85),
    (UserIntent.ANALYTICS, r"\b(spend|analytics|report|breakdown|vendor)\b", 0.75),
]


class IntentDetector:
    def detect(self, text: str) -> IntentResult:
        lowered = text.strip().lower()
        for intent, pattern, conf in _PATTERNS:
            if re.search(pattern, lowered, re.IGNORECASE):
                return IntentResult(intent=intent, confidence=conf, hints={"matched": pattern})
        return IntentResult(intent=UserIntent.GENERAL_CHAT, confidence=0.5, hints={})

    def detect_conversation(
        self,
        text: str,
        *,
        last_assistant_message: Optional[str] = None,
    ) -> ConversationIntentType:
        """Detect social intents that should bypass the LLM."""
        raw = (text or "").strip()
        if not raw:
            return ConversationIntentType.NONE

        normalized = _normalize_message(raw)

        if _NAME_INTRO.search(raw):
            return ConversationIntentType.NAME_INTRO

        if _HOW_ARE_YOU.search(raw) and not _looks_like_expense_question(raw):
            return ConversationIntentType.HOW_ARE_YOU

        if _WHAT_CAN_YOU_DO.search(raw):
            return ConversationIntentType.QUESTION

        if _CASUAL_CHECKIN.search(raw) and not _looks_like_expense_question(raw):
            return ConversationIntentType.SMALL_TALK

        if normalized in _GREETINGS or any(
            normalized.startswith(g) for g in ("good morning", "good afternoon", "good evening")
        ):
            return ConversationIntentType.GREETING

        if normalized in _GRATITUDE or normalized.startswith("thank"):
            return ConversationIntentType.GRATITUDE

        if normalized in _POSITIVE_REPLIES and _assistant_asked_wellbeing(last_assistant_message):
            return ConversationIntentType.POSITIVE_REPLY

        return ConversationIntentType.NONE


def _assistant_asked_wellbeing(last_assistant: Optional[str]) -> bool:
    if not last_assistant:
        return False
    lowered = last_assistant.lower()
    markers = (
        "how are you",
        "how are you doing",
        "how's your day",
        "how is your day",
        "how have you been",
        "good to see you",
        "good to hear from you",
    )
    return any(m in lowered for m in markers)


def _looks_like_expense_question(text: str) -> bool:
    lowered = text.lower()
    expense_kw = (
        "expense", "bill", "receipt", "claim", "reimburse", "submit",
        "approve", "₹", "rs ", "rupee", "amount", "vendor",
    )
    return any(k in lowered for k in expense_kw)


def is_conversational_message(
    text: str,
    *,
    last_assistant_message: Optional[str] = None,
) -> bool:
    """True when the message should bypass LLM/tool planning (greetings, small talk)."""
    return (
        IntentDetector().detect_conversation(
            text, last_assistant_message=last_assistant_message
        )
        != ConversationIntentType.NONE
    )
