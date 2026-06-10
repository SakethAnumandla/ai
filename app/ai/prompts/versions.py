"""Versioned system prompts for debugging, rollback, and role-specific behavior."""
from typing import TYPE_CHECKING, Optional

from app.ai.models.entities import AIPromptVersion
from app.ai.prompts.system import EXPENSE_ASSISTANT_SYSTEM_PROMPT
from app.models import User, UserRole

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# In-code fallbacks (prompt_key → content)
_BUILTIN_PROMPTS = {
    "employee_prompt_v1": (
        "You are an expense assistant for employees. Help create and submit personal expenses. "
        "Never execute financial actions without user confirmation. Be concise."
    ),
    "finance_prompt_v2": (
        "You are a finance operations assistant. Help review claims, approvals, and reimbursements. "
        "Apply policy strictly. Escalate high-value or suspicious items. Never auto-approve."
    ),
    "default_prompt_v1": EXPENSE_ASSISTANT_SYSTEM_PROMPT,
}


class PromptResolver:
    def __init__(self, db: Optional["Session"] = None):
        self._db = db

    def _role_prompt_key(self, user: Optional[User]) -> str:
        if user is None:
            return "default_prompt_v1"
        if user.role in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN):
            return "finance_prompt_v2"
        return "employee_prompt_v1"

    def resolve(self, user: Optional[User] = None, *, prompt_key: Optional[str] = None) -> tuple[str, str]:
        """Returns (content, prompt_key_used)."""
        key = prompt_key or self._role_prompt_key(user)

        if self._db:
            row = (
                self._db.query(AIPromptVersion)
                .filter(AIPromptVersion.prompt_key == key, AIPromptVersion.active.is_(True))
                .order_by(AIPromptVersion.version.desc())
                .first()
            )
            if row:
                return row.content, key

        content = _BUILTIN_PROMPTS.get(key, _BUILTIN_PROMPTS["default_prompt_v1"])
        return content, key
