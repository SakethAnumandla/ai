"""Soft memory forgetting — importance decays over time instead of hard deletes only."""
from datetime import datetime, timezone
from typing import Optional

from app.config import settings


class SoftForgettingEngine:
    """Exponential importance decay based on age since last use."""

    def __init__(
        self,
        *,
        half_life_days: Optional[float] = None,
        floor: Optional[float] = None,
    ):
        self._half_life = half_life_days or settings.ai_memory_soft_half_life_days
        self._floor = floor or settings.ai_memory_soft_floor_importance

    def _age_days(self, ts: Optional[datetime]) -> float:
        if ts is None:
            return 0.0
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400)

    def decayed_importance(
        self,
        base_importance: float,
        *,
        last_used_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
    ) -> float:
        ref = last_used_at or created_at
        days = self._age_days(ref)
        if days <= 0:
            return base_importance
        factor = 0.5 ** (days / self._half_life)
        decayed = base_importance * factor
        return max(self._floor, decayed)

    def should_hard_expire(
        self,
        decayed_importance: float,
        memory_type: str,
        *,
        threshold: Optional[float] = None,
    ) -> bool:
        """Only ephemeral types hard-delete; preferences/graph soft-decay indefinitely."""
        thresh = threshold or settings.ai_memory_decay_low_importance_threshold
        if memory_type in ("preference", "graph"):
            return False
        return decayed_importance < thresh
