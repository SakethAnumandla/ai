"""KPI alerting — budget spikes, policy surges, SLA breaches with priority tiers."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.config import settings
from app.finance.alert_correlation import correlate_alerts
from app.finance.alert_priority import priority_sort_key, resolve_priority
from app.finance.approval_delays import ApprovalDelayAnalyticsService
from app.finance.finance_analytics import FinanceAnalyticsService
from app.finance.models import KPIAlert
from app.finance.policy_violations import PolicyViolationAnalyticsService
from app.models import User


class KPIAlertService:
    def __init__(self, db: Session):
        self._db = db
        self._finance = FinanceAnalyticsService(db)
        self._policy = PolicyViolationAnalyticsService(db)
        self._delays = ApprovalDelayAnalyticsService(db)

    def evaluate_and_persist(self, user: User) -> Dict[str, Any]:
        tenant_id = resolve_tenant_id(user)
        candidates = self.evaluate(user)
        created: List[KPIAlert] = []
        correlation_id: Optional[str] = None

        if len(candidates) >= 2 and settings.kpi_alert_correlation_enabled:
            correlation_id = f"inc-{uuid.uuid4().hex[:12]}"

        for item in candidates:
            if self._has_open_duplicate(tenant_id, item["alert_type"]):
                continue
            priority = item.get("priority") or resolve_priority(
                item["alert_type"],
                severity=item.get("severity"),
                details=item.get("details"),
            )
            row = KPIAlert(
                tenant_id=tenant_id,
                alert_type=item["alert_type"],
                severity=item.get("severity", priority),
                priority=priority,
                correlation_id=correlation_id,
                title=item["title"],
                message=item["message"],
                details=item.get("details", {}),
                status="open",
            )
            self._db.add(row)
            created.append(row)
        if created:
            self._db.commit()
            for row in created:
                self._db.refresh(row)

        incidents = []
        if settings.kpi_alert_correlation_enabled:
            open_alerts = self.list_alerts(tenant_id, status="open", limit=100)
            incidents = correlate_alerts(open_alerts)

        return {
            "created": created,
            "incidents": incidents,
            "correlation_id": correlation_id,
        }

    def evaluate(self, user: User) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        alerts.extend(self._check_budget_spike(user))
        alerts.extend(self._check_policy_surge(user))
        alerts.extend(self._check_sla_breach())
        return alerts

    def list_alerts(
        self,
        tenant_id: int,
        *,
        status: str = "open",
        priority: Optional[str] = None,
        limit: int = 50,
    ) -> List[KPIAlert]:
        q = self._db.query(KPIAlert).filter(KPIAlert.tenant_id == tenant_id)
        if status:
            q = q.filter(KPIAlert.status == status)
        if priority:
            q = q.filter(KPIAlert.priority == priority)
        rows = q.order_by(KPIAlert.created_at.desc()).limit(limit * 2).all()
        rows.sort(key=lambda r: (priority_sort_key(r.priority or "medium"), r.created_at or datetime.min))
        return rows[:limit]

    def acknowledge(self, alert_id: int, user: User) -> Optional[KPIAlert]:
        tenant_id = resolve_tenant_id(user)
        row = (
            self._db.query(KPIAlert)
            .filter(KPIAlert.id == alert_id, KPIAlert.tenant_id == tenant_id)
            .first()
        )
        if not row:
            return None
        row.status = "acknowledged"
        row.acknowledged_by = user.id
        row.acknowledged_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(row)
        return row

    def _check_budget_spike(self, user: User) -> List[Dict[str, Any]]:
        trends = self._finance.spend_trends(user, quarters=1)
        mom = trends.get("mom_changes") or []
        if len(mom) < 2:
            return []
        latest = mom[-1]
        pct = latest.get("mom_pct")
        if pct is None or pct < settings.kpi_alert_budget_spike_pct:
            return []
        details = {"month": latest.get("month"), "mom_pct": pct, "spend": latest.get("spend")}
        priority = resolve_priority("budget_spike", details=details)
        severity = "high" if priority in ("critical", "high") else "medium"
        return [{
            "alert_type": "budget_spike",
            "severity": severity,
            "priority": priority,
            "title": "Monthly spend spike detected",
            "message": (
                f"Spend in {latest.get('month')} rose {pct:+.1f}% month-over-month "
                f"(threshold {settings.kpi_alert_budget_spike_pct}%)."
            ),
            "details": details,
        }]

    def _check_policy_surge(self, user: User) -> List[Dict[str, Any]]:
        summary = self._policy.violation_summary(user, months=1)
        count = summary.get("violation_count", 0)
        if count < settings.kpi_alert_policy_surge_count:
            return []
        top = (summary.get("by_department") or [{}])[0]
        details = {
            "violation_count": count,
            "top_department": top.get("department") if isinstance(top, dict) else None,
        }
        priority = resolve_priority("policy_surge", details=details)
        severity = "high" if priority in ("critical", "high") else "medium"
        return [{
            "alert_type": "policy_surge",
            "severity": severity,
            "priority": priority,
            "title": "Policy violation surge",
            "message": (
                f"{count} policy violations in the last month "
                f"(threshold {settings.kpi_alert_policy_surge_count})."
            ),
            "details": details,
        }]

    def _check_sla_breach(self) -> List[Dict[str, Any]]:
        health = self._delays.company_queue_health()
        overdue_pct = health.get("overdue_pct", 0)
        if overdue_pct < settings.kpi_alert_sla_overdue_pct:
            return []
        priority = resolve_priority("sla_breach", details=health)
        severity = "critical" if priority == "critical" else "high"
        return [{
            "alert_type": "sla_breach",
            "severity": severity,
            "priority": priority,
            "title": "Approval SLA breach risk",
            "message": (
                f"{health.get('overdue_count', 0)} approvals overdue "
                f"({overdue_pct}% of queue, threshold {settings.kpi_alert_sla_overdue_pct}%)."
            ),
            "details": health,
        }]

    def _has_open_duplicate(self, tenant_id: int, alert_type: str) -> bool:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        existing = (
            self._db.query(KPIAlert)
            .filter(
                KPIAlert.tenant_id == tenant_id,
                KPIAlert.alert_type == alert_type,
                KPIAlert.status == "open",
                KPIAlert.created_at >= since,
            )
            .first()
        )
        return existing is not None
