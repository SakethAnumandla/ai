"""Token budget manager — estimate, trim, compress to prevent context overflow."""
import logging
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4


class TokenBudgetManager:
    """
    Keeps conversation context within model limits.

    Responsibilities: estimate usage, trim history, flag compression need.
    """

    def __init__(
        self,
        *,
        max_prompt_tokens: Optional[int] = None,
        reserve_completion_tokens: int = 1024,
    ):
        self.max_prompt_tokens = max_prompt_tokens or settings.ai_max_prompt_tokens
        self.reserve_completion_tokens = reserve_completion_tokens

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // _CHARS_PER_TOKEN)

    def estimate_messages_tokens(self, messages: List[Dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content") or ""
            if isinstance(content, str):
                total += self.estimate_tokens(content)
            elif isinstance(content, list):
                total += sum(
                    self.estimate_tokens(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict)
                )
            total += 4  # per-message overhead
        return total

    def available_budget(self) -> int:
        return max(
            512,
            self.max_prompt_tokens - self.reserve_completion_tokens,
        )

    def trim_messages(
        self,
        messages: List[Dict[str, Any]],
        *,
        keep_system: bool = True,
        min_recent: int = 4,
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Drop oldest non-system messages until within budget.
        Returns (trimmed_messages, estimated_tokens).
        """
        budget = self.available_budget()
        if self.estimate_messages_tokens(messages) <= budget:
            return messages, self.estimate_messages_tokens(messages)

        system_msgs = [m for m in messages if m.get("role") == "system"] if keep_system else []
        other = [m for m in messages if m.get("role") != "system"] if keep_system else list(messages)

        trimmed = list(system_msgs)
        dropped = 0
        while other and self.estimate_messages_tokens(trimmed + other) > budget:
            if len(other) <= min_recent:
                break
            other.pop(0)
            dropped += 1

        trimmed.extend(other)
        tokens = self.estimate_messages_tokens(trimmed)
        if dropped:
            logger.info(
                "token_budget.trimmed",
                extra={"dropped_messages": dropped, "estimated_tokens": tokens, "budget": budget},
            )
        return trimmed, tokens

    def needs_compression(self, messages: List[Dict[str, Any]]) -> bool:
        return self.estimate_messages_tokens(messages) > int(self.available_budget() * 0.85)
