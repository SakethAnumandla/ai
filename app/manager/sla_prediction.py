"""SLA breach prediction — claims likely to miss approval SLA."""
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.manager.approval_insight import ApprovalInsightService
from app.manager.schemas import SLABreachPrediction
from app.manager.workload_analytics import ManagerWorkloadAnalyticsService
from app.models import User


class SLABreachPredictor:
    """
    Predict pending approvals at risk of breaching SLA.

    Uses wait time, approver backlog, and historical delay patterns.
    """

    def __init__(self, db: Session):
        self._db = db
        self._sla_hours = getattr(settings, "manager_approval_urgent_hours", 48.0)
        self._insight = ApprovalInsightService(db)
        self._workload = ManagerWorkloadAnalyticsService(db)

    def predict_at_risk(
        self,
        approver: User,
        *,
        limit: int = 25,
    ) -> List[SLABreachPrediction]:
        prioritized = self._insight.list_prioritized_pending(approver.id)
        backlog = self._workload.pending_backlog_by_approver()
        approver_backlog = next(
            (b["pending_count"] for b in backlog.get("backlog", []) if b["approver_id"] == approver.id),
            len(prioritized),
        )

        delay_stats = self._workload.manager_delay_leaderboard(days=30, limit=50)
        avg_hours = 24.0
        for m in delay_stats.get("managers", []):
            if m["approver_id"] == approver.id:
                avg_hours = m.get("avg_hours_to_action", 24.0)
                break

        predictions: List[SLABreachPrediction] = []
        now = datetime.utcnow()

        for item in prioritized[:limit * 2]:
            hours = item.hours_waiting
            remaining = max(0.0, self._sla_hours - hours)
            prob = self._breach_probability(
                hours_waiting=hours,
                backlog=approver_backlog,
                avg_approver_hours=avg_hours,
            )
            if prob < 0.25:
                continue

            reasons = list(item.urgency_reasons)
            if hours >= self._sla_hours * 0.75:
                reasons.append(f"already at {hours:.0f}h of {self._sla_hours:.0f}h SLA")
            if backlog > 10:
                reasons.append(f"approver backlog: {backlog} pending")
            if avg_hours > self._sla_hours * 0.5:
                reasons.append(f"historical avg delay {avg_hours:.0f}h")

            expected_breach = None
            if prob >= 0.5 and remaining > 0:
                expected_breach = now + timedelta(hours=remaining)

            predictions.append(
                SLABreachPrediction(
                    approval_id=item.approval_id,
                    claim_id=item.claim_id,
                    claim_number=item.claim_number,
                    breach_probability=round(prob, 3),
                    hours_waiting=hours,
                    sla_hours=self._sla_hours,
                    expected_breach_at=expected_breach,
                    reasons=reasons,
                )
            )

        predictions.sort(key=lambda x: -x.breach_probability)
        return predictions[:limit]

    def _breach_probability(
        self,
        *,
        hours_waiting: float,
        backlog: int,
        avg_approver_hours: float,
    ) -> float:
        p = 0.0
        ratio = hours_waiting / max(self._sla_hours, 1)
        p += min(0.5, ratio * 0.45)
        if backlog > 15:
            p += 0.2
        elif backlog > 8:
            p += 0.1
        if avg_approver_hours > self._sla_hours:
            p += 0.25
        elif avg_approver_hours > self._sla_hours * 0.7:
            p += 0.12
        return min(1.0, p)
