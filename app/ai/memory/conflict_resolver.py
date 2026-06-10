"""Preference conflict resolution — confidence decay and evolution."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple  # noqa: F401

from app.ai.schemas.memory_intelligence import ConflictResolution
from app.config import settings


def _parse_ts(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


class PreferenceConflictResolver:
    """
    When new behavior conflicts with stored preference (e.g. UPI vs credit card),
    decay stale confidence and evolve only with sustained evidence.
    """

    def __init__(
        self,
        *,
        decay_factor: Optional[float] = None,
        evolve_min_recent: Optional[int] = None,
        evolve_window_days: Optional[int] = None,
    ):
        self._decay = decay_factor or settings.ai_pref_conflict_decay_factor
        self._evolve_min = evolve_min_recent or settings.ai_pref_evolve_min_recent
        self._evolve_window_days = evolve_window_days or settings.ai_pref_evolve_window_days

    def _recent_weight(self, candidate: Dict[str, Any], now: datetime) -> int:
        last = _parse_ts(candidate.get("last_used_at"))
        if not last:
            return 0
        age_days = (now - last).days
        if age_days <= self._evolve_window_days:
            return int(candidate.get("count", 0))
        return 0

    def resolve_payment_conflict(
        self,
        store: Dict[str, Any],
        new_method: str,
        *,
        category: Optional[str] = None,
        observation_weight: float = 1.0,
    ) -> ConflictResolution:
        now = datetime.now(timezone.utc)
        candidates: Dict[str, Dict[str, Any]] = dict(store.get("candidates") or {})
        primary = store.get("payment_method")
        primary_conf = float(store.get("primary_confidence", 0.5))

        if new_method not in candidates:
            candidates[new_method] = {
                "count": 0,
                "weighted_count": 0.0,
                "confidence": 0.35,
                "last_used_at": None,
                "category_counts": {},
            }

        entry = candidates[new_method]
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["weighted_count"] = float(entry.get("weighted_count", 0)) + observation_weight
        entry["last_used_at"] = now.isoformat()
        if category:
            cc = dict(entry.get("category_counts") or {})
            cc[category] = int(cc.get(category, 0)) + 1
            entry["category_counts"] = cc

        evolved = False
        decayed: List[str] = []
        explanation_parts: List[str] = []

        if primary and primary != new_method:
            old = candidates.get(primary, {})
            old_conf = float(old.get("confidence", primary_conf))
            old["confidence"] = max(0.1, old_conf * self._decay)
            candidates[primary] = old
            decayed.append(primary)
            explanation_parts.append(
                f"Reduced confidence in {primary.replace('_', ' ')} after recent {new_method.replace('_', ' ')} use."
            )

        new_conf = min(
            0.95,
            0.35 + float(entry["weighted_count"]) * 0.08,
        )
        entry["confidence"] = new_conf
        candidates[new_method] = entry

        recent_new = self._recent_weight(entry, now)
        if (
            primary
            and primary != new_method
            and recent_new >= self._evolve_min
            and new_conf > float(candidates.get(primary, {}).get("confidence", 0))
        ):
            store["payment_method"] = new_method
            store["primary_confidence"] = new_conf
            store["evolved_at"] = now.isoformat()
            evolved = True
            explanation_parts.append(
                f"Preferred payment evolved to {new_method.replace('_', ' ')} based on recent usage."
            )
        elif not primary or evolved is False:
            if not primary or new_conf > primary_conf:
                store["payment_method"] = new_method
                store["primary_confidence"] = new_conf
            else:
                store["primary_confidence"] = float(candidates.get(primary, {}).get("confidence", primary_conf))

        store["candidates"] = candidates
        store["count"] = sum(int(c.get("count", 0)) for c in candidates.values())

        return ConflictResolution(
            primary_value=store.get("payment_method", new_method),
            primary_confidence=float(store.get("primary_confidence", new_conf)),
            evolved=evolved,
            decayed_values=decayed,
            explanation=" ".join(explanation_parts) if explanation_parts else None,
        )

    def resolve_vendor_conflict(
        self,
        store: Dict[str, Any],
        vendor_name: str,
        observation_weight: float = 1.0,
    ) -> ConflictResolution:
        """Vendors are keyed per vendor; track confidence separately."""
        now = datetime.now(timezone.utc)
        wc = float(store.get("weighted_count", 0)) + observation_weight
        store["weighted_count"] = wc
        store["count"] = int(store.get("count", 0)) + 1
        store["last_used_at"] = now.isoformat()
        conf = min(0.95, 0.3 + wc * 0.07)
        store["confidence"] = conf
        return ConflictResolution(
            primary_value=vendor_name,
            primary_confidence=conf,
            evolved=False,
        )

    def winning_candidate(
        self, candidates: Dict[str, Dict[str, Any]], *, category: Optional[str] = None
    ) -> Tuple[Optional[str], float]:
        best_key: Optional[str] = None
        best_score = -1.0
        for key, data in candidates.items():
            score = float(data.get("confidence", 0))
            if category:
                cc = data.get("category_counts") or {}
                score += 0.05 * int(cc.get(category, 0))
            if score > best_score:
                best_score = score
                best_key = key
        return best_key, best_score
