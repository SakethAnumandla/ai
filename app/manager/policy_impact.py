"""Policy impact analytics — which policies drive escalations and friction."""
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.manager.models import ApprovalEscalation
from app.models import Claim, ClaimStatus, Policy


class PolicyImpactAnalyticsService:
    """
    Rank policies by escalations, rejections, and approval friction.

    Future: nightly materialized view `policy_impact_stats`.
    """

    def __init__(self, db: Session):
        self._db = db

    def summarize(
        self,
        *,
        tenant_id: int,
        limit: int = 20,
    ) -> Dict[str, Any]:
        escalation_counts: Dict[int, int] = defaultdict(int)
        esc_rows = (
            self._db.query(ApprovalEscalation)
            .filter(
                ApprovalEscalation.tenant_id == tenant_id,
            )
            .limit(1000)
            .all()
        )
        for esc in esc_rows:
            claim_id = esc.claim_id
            claim = self._db.query(Claim).filter(Claim.id == claim_id).first()
            if claim and claim.policy_id:
                escalation_counts[claim.policy_id] += 1

        rejection_counts: Dict[int, int] = defaultdict(int)
        rejected = (
            self._db.query(Claim.policy_id)
            .filter(Claim.status == ClaimStatus.REJECTED)
            .limit(500)
            .all()
        )
        for (policy_id,) in rejected:
            if policy_id:
                rejection_counts[policy_id] += 1

        policy_ids = set(escalation_counts) | set(rejection_counts)
        ranked: List[Dict[str, Any]] = []
        for pid in policy_ids:
            policy = self._db.query(Policy).filter(Policy.id == pid).first()
            ranked.append({
                "policy_id": pid,
                "policy_name": policy.policy_name if policy else None,
                "escalation_count": escalation_counts.get(pid, 0),
                "rejection_count": rejection_counts.get(pid, 0),
                "impact_score": round(
                    escalation_counts.get(pid, 0) * 2 + rejection_counts.get(pid, 0),
                    2,
                ),
            })

        ranked.sort(key=lambda x: -x["impact_score"])
        return {
            "tenant_id": tenant_id,
            "policies": ranked[:limit],
            "note": "Impact score is a simple escalation×2 + rejection heuristic until Phase 6 analytics jobs.",
        }
