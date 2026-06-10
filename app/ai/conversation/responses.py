"""Template replies for greetings, small talk, and gratitude — no LLM required."""
from typing import Optional

from app.ai.conversation.name_utils import extract_name_from_text, parse_name_from_message
from app.ai.orchestrator.intent import ConversationIntentType

# Disabled until preferred_name is verified per user/tenant (prevents wrong-name greetings).
USE_PREFERRED_NAME_IN_GREETINGS = False


class ConversationalResponseService:
    """Human-like replies for social intents."""

    def greeting(self, user_name: Optional[str] = None, *, returning: bool = False) -> str:
        if returning:
            if user_name:
                return f"Hey {user_name}! 👋 Welcome back. How can I help today?"
            return "Hey again! 👋 Good to see you. What's on your mind?"
        if user_name:
            return f"Hey {user_name}! 👋 How are you doing today?"
        return "Hey! 👋 How are you doing today?"

    def how_are_you(self, user_name: Optional[str] = None) -> str:
        name_bit = f", {user_name}" if user_name else ""
        return (
            f"I'm doing great, thanks for asking{name_bit} 😊. "
            "How's your day going?"
        )

    def gratitude(self, user_name: Optional[str] = None) -> str:
        name_bit = f", {user_name}" if user_name else ""
        return (
            f"You're very welcome{name_bit} 😊. "
            "Let me know if I can help with anything."
        )

    def positive_followup(self, user_name: Optional[str] = None) -> str:
        name_bit = f", {name}" if (name := user_name) else ""
        return (
            f"Glad to hear that{name_bit} 😊. "
            "What's been keeping you busy today?"
        )

    def soft_expense_nudge(self) -> str:
        return "Need help with expenses or approvals? I'm here whenever you are."

    def casual_checkin(self, user_name: Optional[str] = None) -> str:
        name_bit = f", {user_name}" if user_name else ""
        return (
            f"All good on my end{name_bit}! How's your day going?"
        )

    def what_can_you_do(self) -> str:
        return (
            "I'm Bizwy AI — I can help with expenses, approvals, reimbursements, "
            "analytics, and executive insights. Or we can just chat — ask me anything."
        )

    def bot_identity(self) -> str:
        return (
            "I'm Bizwy AI, your expense and business assistant. "
            "I can help with expenses, approvals, reimbursements, and analytics."
        )

    def name_intro(self, name: str) -> str:
        return (
            f"Nice to meet you, {name}! I'll remember that. "
            "How's your day going?"
        )

    def welcome_back(self, name: str) -> str:
        return f"Hey {name}! 👋 Welcome back. How are you doing today?"

    def reply_for_intent(
        self,
        intent: ConversationIntentType,
        message: str,
        *,
        preferred_name: Optional[str] = None,
        last_assistant_message: Optional[str] = None,
    ) -> Optional[str]:
        """Build a reply for a conversation intent, or None to fall through to the LLM."""
        lowered = (message or "").strip().lower()
        if "how are you" in lowered or "how r u" in lowered:
            intent = ConversationIntentType.HOW_ARE_YOU

        name = preferred_name if USE_PREFERRED_NAME_IN_GREETINGS else None
        if intent == ConversationIntentType.NAME_INTRO:
            learned = extract_name_from_text(message) or _parse_name(message)
            if learned:
                return self.name_intro(learned)
            return None

        if intent == ConversationIntentType.GREETING:
            returning = bool(last_assistant_message)
            if preferred_name and returning:
                return self.welcome_back(preferred_name)
            return self.greeting(name, returning=returning)

        if intent == ConversationIntentType.GRATITUDE:
            return self.gratitude(name)

        if intent == ConversationIntentType.HOW_ARE_YOU:
            return self.how_are_you(name)

        if intent == ConversationIntentType.SMALL_TALK:
            return self.casual_checkin(name)

        if intent == ConversationIntentType.QUESTION:
            if "name" in lowered or "who are you" in lowered:
                return self.bot_identity()
            return self.what_can_you_do()

        if intent == ConversationIntentType.POSITIVE_REPLY:
            reply = self.positive_followup(name)
            return f"{reply}\n\n{self.soft_expense_nudge()}"

        return None


_parse_name = parse_name_from_message
