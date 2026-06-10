"""Manager workload analytics — approval delay patterns (Phase 6 foundation)."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import ApprovalStatus, ClaimApproval, User, UserRole


class ManagerWorkloadAnalyticsService:
    """
    Identify managers who delay approvals most.
    Phase 6: dashboards, SLA breaches, notifications.
    """

    def __init__(self, db: Session):
        self._db = db

    def manager_delay_leaderboard(
        self,
        *,
        days: int = 30,
        limit: int = 20,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=days)
        q = (
            self._db.query(ClaimApproval)
            .join(User, ClaimApproval.approver_id == User.id)
            .filter(
                ClaimApproval.status.in_([ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]),
                ClaimApproval.actioned_at.isnot(None),
                ClaimApproval.assigned_at >= since,
                User.role.in_([UserRole.MANAGER, UserRole.DEPARTMENT_HEAD]),
            )
        )
        if department:
            from app.models import Department
            try:
                q = q.filter(User.department == Department(department))
            except ValueError:
                pass

        by_approver: Dict[int, List[float]] = {}
        for row in q.all():
            assigned = row.assigned_at
            actioned = row.actioned_at
            if not assigned or not actioned:
                continue
            if assigned.tzinfo:
                assigned = assigned.replace(tzinfo=None)
            if actioned.tzinfo:
                actioned = actioned.replace(tzinfo=None)
            hours = (actioned - assigned).total_seconds() / 3600
            by_approver.setdefault(row.approver_id, []).append(hours)

        leaders: List[Dict[str, Any]] = []
        for approver_id, hours_list in by_approver.items():
            if not hours_list:
                continue
            approver = self._db.query(User).filter(User.id == approver_id).first()
            avg_hours = sum(hours_list) / len(hours_list)
            leaders.append({
                "approver_id": approver_id,
                "name": (approver.full_name or approver.email) if approver else str(approver_id),
                "department": approver.department.value if approver and approver.department else None,
                "avg_hours_to_action": round(avg_hours, 1),
                "completed_count": len(hours_list),
            })

        leaders.sort(key=lambda x: -x["avg_hours_to_action"])
        return {
            "period_days": days,
            "managers": leaders[:limit],
            "note": "Phase 6 will add SLA targets, alerts, and team drill-down.",
        }

    def pending_backlog_by_approver(self, limit: int = 20) -> Dict[str, Any]:
        rows = (
            self._db.query(ClaimApproval)
            .filter(ClaimApproval.status == ApprovalStatus.PENDING)
            .all()
        )
        counts: Dict[int, int] = {}
        for r in rows:
            counts[r.approver_id] = counts.get(r.approver_id, 0) + 1
        ranked = sorted(counts.items(), key=lambda x: -x[1])[:limit]
        out = []
        for approver_id, pending in ranked:
            u = self._db.query(User).filter(User.id == approver_id).first()
            out.append({
                "approver_id": approver_id,
                "name": (u.full_name or u.email) if u else str(approver_id),
                "pending_count": pending,
            })
        return {"backlog": out}
