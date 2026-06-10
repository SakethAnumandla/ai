"""OrganizationEfficiencyService — workflow efficiency scoring."""
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.executive.narratives import ExecutiveNarrativeService
from app.executive.scope import is_full_executive
from app.finance.approval_delays import ApprovalDelayAnalyticsService
from app.finance.reimbursement_ageing import ReimbursementAgeingService
from app.finance.services import FinanceAnalyticsFacade
from app.models import User


class OrganizationEfficiencyService:
    def __init__(self, db: Session):
        self._db = db
        self._facade = FinanceAnalyticsFacade(db)
        self._delays = ApprovalDelayAnalyticsService(db)
        self._reimb = ReimbursementAgeingService(db)
        self._narrative = ExecutiveNarrativeService()

    def score(
        self,
        user: User,
        *,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        tenant_id = resolve_tenant_id(user)
        queue = self._delays.company_queue_health()
        reimb = self._reimb.ageing_report(user)
        dept_trends = self._facade.department_trends(user, tenant_id, months=3)

        dept_scores: Dict[str, float] = defaultdict(lambda: 100.0)
        bottlenecks: List[Dict[str, Any]] = []

        for dept in queue.get("slow_departments", [])[:10]:
            name = dept.get("department", "unknown")
            if department and name != department:
                continue
            wait = dept.get("avg_hours_waiting", 0)
            penalty = min(wait * 0.5, 40)
            dept_scores[name] -= penalty
            bottlenecks.append({
                "department": name,
                "issue": "approval_bottleneck",
                "avg_hours_waiting": wait,
                "impact_score": round(penalty, 1),
            })

        reimb_by_dept: Dict[str, int] = defaultdict(int)
        for item in reimb.get("pending_reimbursement", []):
            reimb_by_dept[item.get("department", "unknown")] += 1
        for item in reimb.get("sla_at_risk", []):
            reimb_by_dept[item.get("department", "unknown")] += 1

        for name, count in reimb_by_dept.items():
            if department and name != department:
                continue
            penalty = min(count * 3, 30)
            dept_scores[name] -= penalty
            bottlenecks.append({
                "department": name,
                "issue": "reimbursement_delay",
                "pending_count": count,
                "impact_score": round(penalty, 1),
            })

        bottlenecks.sort(key=lambda x: -x.get("impact_score", 0))
        if department:
            org_score = max(0, min(100, dept_scores.get(department, 85)))
        else:
            scores = list(dept_scores.values()) or [85]
            org_score = round(max(0, min(100, sum(scores) / len(scores))), 1)

        top_bottlenecks = bottlenecks[:5]
        payload = {
            "efficiency_score": org_score,
            "department_scores": {
                k: round(max(0, min(100, v)), 1) for k, v in sorted(
                    dept_scores.items(), key=lambda x: x[1]
                )[:15]
            },
            "top_bottlenecks": top_bottlenecks,
            "queue_health": queue.get("queue_health"),
            "scope": "company" if is_full_executive(user) else "department",
        }
        payload["narrative"] = self._narrative.efficiency_summary(payload)
        if top_bottlenecks:
            b = top_bottlenecks[0]
            dept_name = (b.get("department") or "Operations").title()
            if b.get("issue") == "approval_bottleneck":
                payload["primary_insight"] = (
                    f"Approval bottlenecks in {dept_name} are contributing most to workflow inefficiency."
                )
            else:
                payload["primary_insight"] = (
                    f"Delayed reimbursements in {dept_name} are contributing most to workflow inefficiency."
                )
        return payload

    def department_efficiency(
        self,
        user: User,
        *,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not department and user.department:
            department = user.department.value
        return self.score(user, department=department)
