"""Orchestrate social intent detection and template replies before the LLM."""
from dataclasses import dataclass
from typing import List, Optional

from app.ai.conversation.name_utils import extract_name_from_text, parse_name_from_message
from app.ai.conversation.responses import ConversationalResponseService
from app.ai.orchestrator.intent import ConversationIntentType, IntentDetector


@dataclass
class ConversationalTurnResult:
    handled: bool
    message: Optional[str] = None
    learned_name: Optional[str] = None


class ConversationalHandler:
    def __init__(
        self,
        *,
        intent_detector: Optional[IntentDetector] = None,
        responses: Optional[ConversationalResponseService] = None,
    ):
        self._intent = intent_detector or IntentDetector()
        self._responses = responses or ConversationalResponseService()

    def try_reply(
        self,
        user_content: str,
        *,
        preferred_name: Optional[str] = None,
        recent_user_messages: Optional[List[str]] = None,
        recent_assistant_messages: Optional[List[str]] = None,
    ) -> ConversationalTurnResult:
        text = (user_content or "").strip()
        if not text:
            return ConversationalTurnResult(handled=False)

        recent_user = recent_user_messages or []
        recent_assistant = recent_assistant_messages or []
        last_assistant = recent_assistant[-1] if recent_assistant else None

        learned = extract_name_from_text(text) or parse_name_from_message(text)
        if learned:
            return ConversationalTurnResult(
                handled=True,
                message=self._responses.name_intro(learned),
                learned_name=learned,
            )

        conv_intent = self._intent.detect_conversation(
            text, last_assistant_message=last_assistant
        )
        if conv_intent == ConversationIntentType.NONE:
            return ConversationalTurnResult(handled=False)

        message = self._responses.reply_for_intent(
            conv_intent,
            text,
            preferred_name=preferred_name,
            last_assistant_message=last_assistant,
        )
        if not message:
            return ConversationalTurnResult(handled=False)

        return ConversationalTurnResult(handled=True, message=message)
