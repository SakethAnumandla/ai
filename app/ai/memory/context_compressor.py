"""Compress conversation context when it exceeds configured limits."""
from typing import Any, List


class ContextCompressor:
    """Rule-based compression before LLM summarization."""

    @staticmethod
    def estimate_tokens(messages: List[Any]) -> int:
        stored = sum(m.token_count or 0 for m in messages)
        if stored > 0:
            return stored
        return sum(max(1, len(m.content) // 4) for m in messages)

    @staticmethod
    def compress_messages(
        messages: List[Any],
        *,
        keep_recent: int = 10,
    ) -> tuple[List[Any], str]:
        """
        Keep the most recent messages and return a digest of older ones.
        Returns (kept_messages, digest_of_dropped).
        """
        if len(messages) <= keep_recent:
            return messages, ""

        dropped = messages[:-keep_recent]
        kept = messages[-keep_recent:]
        lines = [f"[{m.role}] {m.content[:200]}" for m in dropped]
        digest = "Earlier conversation (compressed):\n" + "\n".join(lines[:30])
        if len(dropped) > 30:
            digest += f"\n… and {len(dropped) - 30} more messages"
        return kept, digest
