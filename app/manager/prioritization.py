"""Approval queue prioritization — urgent items first."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.manager.schemas import ApprovalCandidate, PrioritizedCandidate
from app.models import ApprovalStatus, ClaimApproval


class ApprovalPrioritizer:
    """
    Rank pending approvals: ageing, high-value, blocked reimbursement, wait time.
    """

    def __init__(self, db: Session):
        self._db = db
        self._urgent_hours = getattr(settings, "manager_approval_urgent_hours", 48.0)
        self._high_amount = getattr(settings, "ai_high_amount_threshold", 50000.0)

    def prioritize(
        self,
        candidates: List[ApprovalCandidate],
        *,
        approver_id: int,
    ) -> List[PrioritizedCandidate]:
        approval_ids = [c.approval_id for c in candidates]
        assigned_map = self._assigned_at_map(approver_id, approval_ids)
        now = datetime.utcnow()

        prioritized: List[PrioritizedCandidate] = []
        for c in candidates:
            assigned = assigned_map.get(c.approval_id)
            hours = 0.0
            if assigned:
                a = assigned.replace(tzinfo=None) if assigned.tzinfo else assigned
                hours = max(0.0, (now - a).total_seconds() / 3600)

            score, reasons = self._priority_score(c, hours_waiting=hours)
            prioritized.append(
                PrioritizedCandidate(
                    **c.model_dump(),
                    priority_score=score,
                    urgency_reasons=reasons,
                    hours_waiting=round(hours, 1),
                )
            )

        prioritized.sort(key=lambda x: -x.priority_score)
        for i, p in enumerate(prioritized, start=1):
            p.priority_rank = i
        return prioritized

    def _priority_score(self, c: ApprovalCandidate, *, hours_waiting: float) -> tuple:
        score = 0.0
        reasons: List[str] = []

        if hours_waiting >= self._urgent_hours:
            score += 0.35
            reasons.append(f"waiting {hours_waiting:.0f}h (>{self._urgent_hours:.0f}h SLA)")
        elif hours_waiting >= self._urgent_hours / 2:
            score += 0.15
            reasons.append(f"ageing {hours_waiting:.0f}h")

        if c.bill_amount >= self._high_amount:
            score += 0.3
            reasons.append("high-value claim")
        elif c.bill_amount >= self._high_amount * 0.5:
            score += 0.1

        if c.risk.risk_score >= 0.5:
            score += 0.2
            reasons.append("elevated risk — review before batch approve")

        if c.policy_flags:
            score += 0.15
            reasons.append("policy flags present")

        if c.risk.risk_flags and "abnormal_reimbursement" in c.risk.risk_flags:
            score += 0.25
            reasons.append("blocked/partial reimbursement pattern")

        if c.risk.risk_flags and "missing_invoice" in c.risk.risk_flags:
            score += 0.1
            reasons.append("missing invoice — employee may be waiting")

        return min(1.0, round(score, 3)), reasons

    def _assigned_at_map(self, approver_id: int, approval_ids: List[int]) -> dict:
        if not approval_ids:
            return {}
        rows = (
            self._db.query(ClaimApproval.id, ClaimApproval.assigned_at)
            .filter(
                ClaimApproval.approver_id == approver_id,
                ClaimApproval.id.in_(approval_ids),
            )
            .all()
        )
        return {r.id: r.assigned_at for r in rows}
