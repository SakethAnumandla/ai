"""Fixed session welcome shown when the user opens chat."""

CHAT_WELCOME_MESSAGE = (
    "Hey! 👋 I'm Bizwy AI.\n\n"
    "I can help with:\n"
    "• Expenses\n"
    "• Approvals\n"
    "• Reimbursements\n"
    "• Analytics\n"
    "• Executive insights\n\n"
    "Or feel free to ask me anything."
)

WELCOME_MESSAGE_METADATA = {"welcome": True}

LEGACY_WELCOME_MARKERS = (
    "Bizwy Expense Assistant",
    "expense-related tasks",
    "How may I assist you",
)


def is_welcome_message(content: str, metadata=None) -> bool:
    if metadata and metadata.get("welcome"):
        return True
    if content == CHAT_WELCOME_MESSAGE:
        return True
    lowered = (content or "").lower()
    return any(marker.lower() in lowered for marker in LEGACY_WELCOME_MARKERS)
