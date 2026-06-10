"""Voice command safety — financial actions NEVER auto-submit."""
import logging
from typing import FrozenSet, Optional

from app.ai.tools.execution_policy import requires_human_confirmation

logger = logging.getLogger(__name__)

# Tools that must NEVER execute without explicit confirmation when session is voice-originated
_VOICE_BLOCKED_AUTO_EXECUTE: FrozenSet[str] = frozenset({
    "expense.submit.v1",
    "expense.submit",
    "approval.submit.v1",
    "approval.submit",
    "reimbursement.submit.v1",
    "reimbursement.submit",
    "expense.delete.v1",
    "expense.delete",
    "expense.update.v1",
    "expense.update",
})

# Voice sessions always require confirmation for ANY mutating financial tool
_VOICE_ALWAYS_CONFIRM: FrozenSet[str] = frozenset({
    "expense.create.v1",
    "expense.submit.v1",
    "approval.submit.v1",
    "reimbursement.submit.v1",
    "expense.delete.v1",
    "expense.update.v1",
})


class VoiceCommandSafety:
    """Enforce stricter confirmation rules for voice-originated sessions."""

    @staticmethod
    def is_voice_session(session_metadata: Optional[dict]) -> bool:
        if not session_metadata:
            return False
        return bool(
            session_metadata.get("voice_originated")
            or session_metadata.get("interaction_source") == "voice"
        )

    @classmethod
    def must_force_confirmation(cls, tool_name: str, *, voice_originated: bool) -> bool:
        if not voice_originated:
            return False
        if tool_name in _VOICE_ALWAYS_CONFIRM:
            return True
        return requires_human_confirmation(tool_name)

    @classmethod
    def block_auto_execute(cls, tool_name: str, *, voice_originated: bool) -> bool:
        """Voice never auto-executes submit/approve/reimburse/delete without confirmation."""
        if not voice_originated:
            return False
        return tool_name in _VOICE_BLOCKED_AUTO_EXECUTE

    @classmethod
    def validate_tool_allowed(
        cls,
        tool_name: str,
        *,
        voice_originated: bool,
        skip_confirmation: bool,
        confirmation_acknowledged: bool = False,
    ) -> Optional[str]:
        """
        Returns error message if execution must be blocked; None if allowed to proceed.
        """
        if not voice_originated:
            return None

        if confirmation_acknowledged:
            return None

        if cls.block_auto_execute(tool_name, voice_originated=True) and skip_confirmation:
            logger.warning("voice.safety.blocked_auto_execute", extra={"tool": tool_name})
            return (
                "Voice commands cannot auto-submit or delete expenses. "
                "Please confirm this action explicitly in the app."
            )

        if cls.must_force_confirmation(tool_name, voice_originated=True) and skip_confirmation:
            return (
                "This action requires explicit confirmation after a voice command. "
                "Say 'yes' or confirm in the app to proceed."
            )
        return None

    @classmethod
    def confirmation_preamble(cls) -> str:
        return (
            "You initiated this via voice. I will not submit or approve expenses "
            "without your explicit confirmation."
        )
