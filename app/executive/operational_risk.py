"""OperationalRiskSummaryService — organizational risk summaries."""
from collections import defaultdict
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.executive.narratives import ExecutiveNarrativeService
from app.finance.approval_delays import ApprovalDelayAnalyticsService
from app.finance.kpi_alerts import KPIAlertService
from app.finance.reimbursement_ageing import ReimbursementAgeingService
from app.finance.services import FinanceAnalyticsFacade
from app.models import User


class OperationalRiskSummaryService:
    def __init__(self, db: Session):
        self._db = db
        self._facade = FinanceAnalyticsFacade(db)
        self._reimb = ReimbursementAgeingService(db)
        self._delays = ApprovalDelayAnalyticsService(db)
        self._kpi = KPIAlertService(db)
        self._narrative = ExecutiveNarrativeService()

    def summary(self, user: User, *, months: int = 3) -> Dict[str, Any]:
        tenant_id = resolve_tenant_id(user)
        reimb = self._reimb.ageing_report(user)
        health = self._facade.approval_health(user, tenant_id)
        policy = self._facade.policy_violations(user, tenant_id, months=months)
        open_alerts = self._kpi.list_alerts(tenant_id, status="open", limit=20)

        risks: List[Dict[str, Any]] = []
        risks.extend(self._reimbursement_risks(reimb))
        risks.extend(self._approval_sla_risks(health))
        risks.extend(self._policy_risks(policy))
        for alert in open_alerts:
            risks.append({
                "risk_type": alert.alert_type,
                "severity": alert.priority or alert.severity,
                "title": alert.title,
                "narrative": alert.message,
            })

        risks.sort(key=lambda r: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
            str(r.get("severity", "medium")), 2
        ))
        bullets = self._narrative.operational_risk_bullets(risks)
        narrative = "\n".join(bullets[:5]) if bullets else "No major operational risks detected."

        return {
            "risks": risks[:15],
            "risk_count": len(risks),
            "narrative": narrative,
            "bullets": bullets[:8],
            "by_category": {
                "reimbursement": len([r for r in risks if r.get("risk_type") == "reimbursement_backlog"]),
                "approval_sla": len([r for r in risks if r.get("risk_type") == "approval_sla"]),
                "policy": len([r for r in risks if r.get("risk_type") == "policy"]),
                "kpi_alert": len([r for r in risks if r.get("risk_type") in (
                    "budget_spike", "policy_surge", "sla_breach"
                )]),
            },
        }

    def _reimbursement_risks(self, reimb: Dict[str, Any]) -> List[Dict[str, Any]]:
        by_dept: Dict[str, int] = defaultdict(int)
        for item in reimb.get("pending_reimbursement", []):
            dept = item.get("department", "unknown")
            by_dept[dept] += 1
        for item in reimb.get("sla_at_risk", []):
            dept = item.get("department", "unknown")
            by_dept[dept] += 1

        risks = []
        for dept, count in sorted(by_dept.items(), key=lambda x: -x[1])[:5]:
            if count < 2:
                continue
            risks.append({
                "risk_type": "reimbursement_backlog",
                "severity": "high" if count >= 5 else "medium",
                "department": dept,
                "title": f"{dept.title()} reimbursement backlog",
                "narrative": (
                    f"{dept.title()} reimbursement backlog has {count} items pending "
                    "or at SLA risk."
                ),
                "count": count,
            })
        return risks

    def _approval_sla_risks(self, health: Dict[str, Any]) -> List[Dict[str, Any]]:
        risks = []
        queue = health.get("queue", {})
        sla = health.get("sla_at_risk") or {}
        by_dept: Dict[str, int] = defaultdict(int)
        for item in sla.get("at_risk", []):
            by_dept[item.get("department", "unknown")] += 1
        for name, pending in sorted(by_dept.items(), key=lambda x: -x[1])[:5]:
            risks.append({
                "risk_type": "approval_sla",
                "severity": "high",
                "department": name,
                "title": f"{name.title()} approvals near SLA breach",
                "narrative": (
                    f"{name.title()} approvals are approaching SLA breach thresholds "
                    f"({pending} at risk)."
                ),
            })
        slow = queue.get("slow_departments") or []
        for dept in slow[:3]:
            risks.append({
                "risk_type": "approval_sla",
                "severity": "medium",
                "department": dept.get("department"),
                "title": "Approval bottleneck",
                "narrative": (
                    f"{dept.get('department', '').title()} averages "
                    f"{dept.get('avg_hours_waiting', 0):.0f}h waiting on approvals."
                ),
            })
        return risks

    def _policy_risks(self, policy: Dict[str, Any]) -> List[Dict[str, Any]]:
        risks = []
        for hotspot in (policy.get("hotspots") or [])[:3]:
            risks.append({
                "risk_type": "policy",
                "severity": "medium",
                "title": f"Policy hotspot: {hotspot.get('name')}",
                "narrative": (
                    f"{hotspot.get('violations', 0)} violations linked to "
                    f"{hotspot.get('type', 'policy')} '{hotspot.get('name')}'."
                ),
            })
        return risks
