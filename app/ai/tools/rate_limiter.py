"""Per-user per-tool rate limiting."""
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

_FINANCIAL_TOOLS = frozenset({
    "expense.submit.v1",
    "approval.submit.v1",
    "reimbursement.submit.v1",
    "expense.delete.v1",
})


@dataclass
class ToolRateLimiter:
    """In-memory sliding window; use Redis in multi-instance production."""

    _windows: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))

    def _key(self, tenant_id: int, user_id: int, tool_name: str) -> str:
        return f"{tenant_id}:{user_id}:{tool_name}"

    def _limit_for(self, tool_name: str) -> int:
        if tool_name in _FINANCIAL_TOOLS:
            return settings.ai_tool_rate_limit_financial
        return settings.ai_tool_rate_limit_default

    def check_and_record(self, *, tenant_id: int, user_id: int, tool_name: str) -> Tuple[bool, Optional[str]]:
        key = self._key(tenant_id, user_id, tool_name)
        limit = self._limit_for(tool_name)
        now = time.monotonic()
        window_start = now - 60.0
        hits = [t for t in self._windows[key] if t > window_start]
        if len(hits) >= limit:
            logger.warning(
                "tool.rate_limited",
                extra={"tool_name": tool_name, "user_id": user_id, "limit": limit},
            )
            return False, f"Rate limit exceeded for {tool_name} ({limit}/minute)"
        hits.append(now)
        self._windows[key] = hits
        return True, None
