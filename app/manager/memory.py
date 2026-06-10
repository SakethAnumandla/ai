"""Manager memory — approval behavior, overrides, escalation tendencies."""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.ai.memory.repository import AIRepository
from app.ai.models.entities import MemoryType
from app.ai.schemas.common import TenantUserContext
from app.ai.schemas.memory import MemoryEntryCreate


class ManagerMemoryService:
    """
    Stores manager approval patterns in Redis (same long-term memory hash as preferences).
    Improves summaries, recommendations, and prioritization.
    """

    KEY_BEHAVIOR = "approval_behavior"

    def __init__(self, db: Session, repo: Optional[AIRepository] = None):
        self._db = db
        self._repo = repo or AIRepository(db)

    def record_decision(
        self,
        ctx: TenantUserContext,
        *,
        decision: str,
        claim_id: int,
        main_category: Optional[str] = None,
        amount: float = 0.0,
        risk_score: float = 0.0,
        was_override: bool = False,
    ) -> None:
        existing = self._load_behavior(ctx)
        stats = existing.get("stats", {
            "approved": 0,
            "rejected": 0,
            "overrides": 0,
            "high_risk_approved": 0,
        })
        cats = existing.get("categories", {})

        if decision == "approved":
            stats["approved"] = stats.get("approved", 0) + 1
            if risk_score >= 0.5:
                stats["high_risk_approved"] = stats.get("high_risk_approved", 0) + 1
        elif decision == "rejected":
            stats["rejected"] = stats.get("rejected", 0) + 1
        if was_override:
            stats["overrides"] = stats.get("overrides", 0) + 1

        if main_category:
            cat = cats.get(main_category, {"count": 0, "total_amount": 0.0})
            cat["count"] += 1
            cat["total_amount"] = round(cat.get("total_amount", 0) + amount, 2)
            cats[main_category] = cat

        self._repo.save_memory(
            ctx,
            MemoryEntryCreate(
                memory_type=MemoryType.CONTEXT,
                memory_key=f"manager:{self.KEY_BEHAVIOR}",
                value={"stats": stats, "categories": cats, "last_claim_id": claim_id},
                importance=0.65,
            ),
        )

    def get_behavior_summary(self, ctx: TenantUserContext) -> Dict[str, Any]:
        data = self._load_behavior(ctx)
        stats = data.get("stats", {})
        lines = []
        if stats.get("approved"):
            lines.append(f"You have approved {stats['approved']} claims via copilot recently.")
        if stats.get("high_risk_approved"):
            lines.append(
                f"{stats['high_risk_approved']} approvals were on medium/high-risk claims."
            )
        if stats.get("overrides"):
            lines.append(f"You frequently override policy flags ({stats['overrides']} times).")
        return {
            "summary": " ".join(lines) if lines else "",
            "stats": stats,
            "categories": data.get("categories", {}),
        }

    def _load_behavior(self, ctx: TenantUserContext) -> Dict[str, Any]:
        rows = self._repo.fetch_memories_by_type(ctx, MemoryType.CONTEXT.value, limit=20)
        for row in rows:
            if row.memory_key == f"manager:{self.KEY_BEHAVIOR}":
                return row.value if isinstance(row.value, dict) else {}
        return {}
