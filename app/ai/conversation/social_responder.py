"""Backward-compatible social turn helpers — prefer ConversationalHandler."""
from dataclasses import dataclass
from typing import List, Optional

from app.ai.conversation.name_utils import extract_name_from_text


@dataclass
class SocialTurnResult:
    handled: bool
    message: Optional[str] = None
    learned_name: Optional[str] = None


def extract_name_from_history(recent_texts: List[str]) -> Optional[str]:
    for text in reversed(recent_texts):
        name = extract_name_from_text(text)
        if name:
            return name
    return None


def try_social_response(
    user_content: str,
    *,
    recent_user_messages: Optional[List[str]] = None,
    recent_assistant_messages: Optional[List[str]] = None,
    preferred_name: Optional[str] = None,
) -> SocialTurnResult:
    """Delegate to ConversationalHandler for social turns."""
    from app.ai.conversation.handler import ConversationalHandler

    turn = ConversationalHandler().try_reply(
        user_content,
        preferred_name=preferred_name,
        recent_user_messages=recent_user_messages,
        recent_assistant_messages=recent_assistant_messages,
    )
    return SocialTurnResult(
        handled=turn.handled,
        message=turn.message,
        learned_name=turn.learned_name,
    )
