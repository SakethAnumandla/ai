"""Manager behavioral risk — unusual approval patterns (future advanced)."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.schemas.common import TenantUserContext
from app.manager.memory import ManagerMemoryService
from app.manager.schemas import BehavioralRiskAssessment
from app.models import ApprovalStatus, ClaimApproval, User


class ManagerBehavioralRiskService:
    """
    Detect unusual manager approval patterns for audit review.
    Never auto-blocks — flags only.
    """

    def __init__(self, db: Session, *, fast_approval_minutes: float = 2.0):
        self._db = db
        self._fast_minutes = fast_approval_minutes
        self._memory = ManagerMemoryService(db)

    def assess_manager(
        self,
        manager_id: int,
        *,
        tenant_id: int,
        lookback_days: int = 30,
    ) -> BehavioralRiskAssessment:
        flags: List[str] = []
        explanations: List[str] = []
        score = 0.0

        since = datetime.utcnow() - timedelta(days=lookback_days)
        completed = (
            self._db.query(ClaimApproval)
            .filter(
                ClaimApproval.approver_id == manager_id,
                ClaimApproval.status.in_([ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]),
                ClaimApproval.actioned_at.isnot(None),
                ClaimApproval.assigned_at >= since,
            )
            .all()
        )

        fast_count = 0
        for row in completed:
            assigned = row.assigned_at
            actioned = row.actioned_at
            if not assigned or not actioned:
                continue
            if assigned.tzinfo:
                assigned = assigned.replace(tzinfo=None)
            if actioned.tzinfo:
                actioned = actioned.replace(tzinfo=None)
            minutes = (actioned - assigned).total_seconds() / 60
            if minutes < self._fast_minutes and (row.approved_amount or 0) > 5000:
                fast_count += 1

        if fast_count >= 3:
            flags.append("unusually_fast_high_value_approvals")
            explanations.append(
                f"{fast_count} high-value approvals completed in under {self._fast_minutes:.0f} minutes."
            )
            score += 0.35

        ctx = TenantUserContext(tenant_id=tenant_id, user_id=manager_id)
        behavior = self._memory.get_behavior_summary(ctx)
        stats = behavior.get("stats", {})
        overrides = stats.get("overrides", 0)
        approved = stats.get("approved", 0)
        high_risk = stats.get("high_risk_approved", 0)

        if approved and overrides / max(approved, 1) > 0.3:
            flags.append("repeated_policy_overrides")
            explanations.append(
                f"Override rate is high ({overrides}/{approved} recent copilot approvals)."
            )
            score += 0.25

        if approved and high_risk / max(approved, 1) > 0.4:
            flags.append("selective_high_risk_approval_pattern")
            explanations.append(
                f"Frequently approves medium/high-risk claims ({high_risk}/{approved})."
            )
            score += 0.2

        score = min(1.0, round(score, 3))
        summary = (
            "No unusual approval patterns detected."
            if not flags
            else " ".join(explanations)
        )

        return BehavioralRiskAssessment(
            manager_id=manager_id,
            risk_score=score,
            risk_flags=flags,
            explanations=explanations,
            summary=summary,
            lookback_days=lookback_days,
            sample_size=len(completed),
        )
