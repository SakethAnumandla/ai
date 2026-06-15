"""Fixed session welcome shown when the user opens chat."""

CHAT_WELCOME_MESSAGE = (
    "Hey! 👋 I'm Bizwy AI — your expense assistant.\n\n"
    "To **create an expense**, you can:\n"
    "• **Upload** a receipt (image or PDF) using 📎 — I'll read it with AI vision\n"
    "• **Enter manually** — say *\"create expense manually\"* and I'll ask each field\n"
    "• **Mix both** — start manually and attach a bill anytime to auto-fill\n\n"
    "You can log **multiple bills** in one chat (e.g. travel and meals). "
    "Incomplete entries are saved as **drafts** until you submit.\n\n"
    "I also help with approvals, reimbursements, and analytics. What would you like to do?"
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
