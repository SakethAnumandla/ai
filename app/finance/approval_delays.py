"""Approval bottleneck analytics — departments, managers, queue health."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ApprovalStatus, ClaimApproval, User, UserRole


class ApprovalDelayAnalyticsService:
    def __init__(self, db: Session):
        self._db = db
        self._sla_hours = getattr(settings, "manager_approval_urgent_hours", 48.0)

    def company_queue_health(self) -> Dict[str, Any]:
        pending = (
            self._db.query(ClaimApproval)
            .filter(ClaimApproval.status == ApprovalStatus.PENDING)
            .all()
        )
        now = datetime.utcnow()
        total = len(pending)
        overdue = 0
        by_dept_hours: Dict[str, List[float]] = defaultdict(list)
        by_approver: Dict[int, int] = defaultdict(int)

        for row in pending:
            by_approver[row.approver_id] += 1
            assigned = row.assigned_at
            if assigned and assigned.tzinfo:
                assigned = assigned.replace(tzinfo=None)
            hours = (now - assigned).total_seconds() / 3600 if assigned else 0
            if hours >= self._sla_hours:
                overdue += 1
            approver = self._db.query(User).filter(User.id == row.approver_id).first()
            dept = approver.department.value if approver and approver.department else "unknown"
            by_dept_hours[dept].append(hours)

        slow_depts = []
        for dept, hours_list in by_dept_hours.items():
            avg = sum(hours_list) / max(len(hours_list), 1)
            slow_depts.append({
                "department": dept,
                "pending_count": len(hours_list),
                "avg_hours_waiting": round(avg, 1),
            })
        slow_depts.sort(key=lambda x: -x["avg_hours_waiting"])

        manager_bottlenecks = []
        for aid, count in sorted(by_approver.items(), key=lambda x: -x[1])[:15]:
            u = self._db.query(User).filter(User.id == aid).first()
            if u and u.role in (UserRole.MANAGER, UserRole.DEPARTMENT_HEAD):
                manager_bottlenecks.append({
                    "approver_id": aid,
                    "name": u.full_name or u.email,
                    "pending_count": count,
                })

        health = "healthy"
        if overdue / max(total, 1) > 0.3:
            health = "critical"
        elif overdue / max(total, 1) > 0.15:
            health = "degraded"

        return {
            "pending_total": total,
            "overdue_count": overdue,
            "overdue_pct": round(overdue / max(total, 1) * 100, 1),
            "queue_health": health,
            "slow_departments": slow_depts[:10],
            "manager_bottlenecks": manager_bottlenecks,
            "sla_hours": self._sla_hours,
        }

    def sla_at_risk_summary(self, *, within_hours: float = 24.0) -> Dict[str, Any]:
        """Approvals likely to breach SLA within N hours."""
        pending = (
            self._db.query(ClaimApproval)
            .filter(ClaimApproval.status == ApprovalStatus.PENDING)
            .all()
        )
        now = datetime.utcnow()
        at_risk = []
        for row in pending:
            assigned = row.assigned_at
            if assigned and assigned.tzinfo:
                assigned = assigned.replace(tzinfo=None)
            hours = (now - assigned).total_seconds() / 3600 if assigned else 0
            remaining = self._sla_hours - hours
            if 0 < remaining <= within_hours:
                approver = self._db.query(User).filter(User.id == row.approver_id).first()
                dept = approver.department.value if approver and approver.department else "unknown"
                at_risk.append({
                    "approval_id": row.id,
                    "claim_id": row.claim_id,
                    "department": dept,
                    "hours_waiting": round(hours, 1),
                    "hours_until_breach": round(remaining, 1),
                })

        at_risk.sort(key=lambda x: x["hours_until_breach"])
        depts = list(dict.fromkeys(a["department"] for a in at_risk))
        narrative = (
            f"{len(at_risk)} approval(s) are at risk of breaching SLA within "
            f"{within_hours:.0f} hours, primarily in {', '.join(depts[:4])}."
            if at_risk
            else "No approvals at immediate SLA breach risk."
        )
        return {
            "at_risk_count": len(at_risk),
            "within_hours": within_hours,
            "at_risk": at_risk[:30],
            "narrative": narrative,
        }

    def manager_delays(self, *, days: int = 30) -> Dict[str, Any]:
        since = datetime.utcnow() - timedelta(days=days)
        completed = (
            self._db.query(ClaimApproval)
            .filter(
                ClaimApproval.status.in_([ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]),
                ClaimApproval.actioned_at.isnot(None),
                ClaimApproval.assigned_at >= since,
            )
            .all()
        )
        by_manager: Dict[int, List[float]] = defaultdict(list)
        for row in completed:
            assigned = row.assigned_at
            actioned = row.actioned_at
            if not assigned or not actioned:
                continue
            if assigned.tzinfo:
                assigned = assigned.replace(tzinfo=None)
            if actioned.tzinfo:
                actioned = actioned.replace(tzinfo=None)
            hours = (actioned - assigned).total_seconds() / 3600
            by_manager[row.approver_id].append(hours)

        ranked = []
        for mid, hours in by_manager.items():
            u = self._db.query(User).filter(User.id == mid).first()
            if not u:
                continue
            ranked.append({
                "approver_id": mid,
                "name": u.full_name or u.email,
                "avg_hours": round(sum(hours) / len(hours), 1),
                "completed": len(hours),
            })
        ranked.sort(key=lambda x: -x["avg_hours"])
        return {"managers": ranked[:20], "period_days": days}
