"""Tests for conversational intent detection and template replies."""
import pytest

from app.ai.conversation.handler import ConversationalHandler
from app.ai.conversation.responses import ConversationalResponseService
from app.ai.orchestrator.intent import ConversationIntentType, IntentDetector


@pytest.fixture
def detector():
    return IntentDetector()


@pytest.fixture
def responses():
    return ConversationalResponseService()


@pytest.fixture
def handler():
    return ConversationalHandler()


class TestConversationIntent:
    def test_greeting_hello(self, detector):
        assert detector.detect_conversation("hello") == ConversationIntentType.GREETING

    def test_greeting_good_morning(self, detector):
        assert detector.detect_conversation("good morning") == ConversationIntentType.GREETING

    def test_gratitude(self, detector):
        assert detector.detect_conversation("thank you") == ConversationIntentType.GRATITUDE

    def test_how_are_you(self, detector):
        assert detector.detect_conversation("how are you") == ConversationIntentType.HOW_ARE_YOU

    def test_name_intro(self, detector):
        assert detector.detect_conversation("my name is Saketh") == ConversationIntentType.NAME_INTRO

    def test_positive_reply_after_greeting(self, detector):
        assert (
            detector.detect_conversation(
                "good",
                last_assistant_message="Hey! 👋 How are you doing today?",
            )
            == ConversationIntentType.POSITIVE_REPLY
        )

    def test_joke_falls_through(self, detector):
        assert detector.detect_conversation("tell me a joke") == ConversationIntentType.NONE


class TestConversationalResponses:
    def test_greeting_template(self, responses):
        assert "👋" in responses.greeting()
        assert "Hey!" in responses.greeting()
        # Names disabled in greetings until memory is verified per user
        from app.ai.conversation import responses as resp_mod
        assert "Saketh" not in resp_mod.ConversationalResponseService().reply_for_intent(
            ConversationIntentType.GREETING,
            "hello",
            preferred_name="Saketh",
        )

    def test_gratitude_template(self, responses):
        msg = responses.gratitude()
        assert "welcome" in msg.lower()

    def test_what_can_you_do(self, responses):
        msg = responses.what_can_you_do()
        assert "expenses" in msg.lower()


class TestConversationalHandler:
    def test_hello_no_llm_path(self, handler):
        turn = handler.try_reply("hello")
        assert turn.handled
        assert "👋" in (turn.message or "")

    def test_thanks(self, handler):
        turn = handler.try_reply("thanks")
        assert turn.handled
        assert "welcome" in (turn.message or "").lower()

    def test_name_learning(self, handler):
        turn = handler.try_reply("my name is Saketh")
        assert turn.handled
        assert turn.learned_name == "Saketh"
        assert "Saketh" in (turn.message or "")

    def test_positive_followup(self, handler):
        turn = handler.try_reply(
            "good",
            recent_assistant_messages=["Hey! 👋 How are you doing today?"],
        )
        assert turn.handled
        assert "Glad to hear" in (turn.message or "")

    def test_joke_not_handled(self, handler):
        turn = handler.try_reply("tell me a joke")
        assert not turn.handled
