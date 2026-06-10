"""KPI alert correlation — group related signals (Phase 7 seed)."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import settings
from app.finance.alert_priority import AlertPriority, priority_sort_key
from app.finance.models import KPIAlert


INCIDENT_OPERATIONAL_STRESS = "operational_stress"
INCIDENT_COMPLIANCE_RISK = "compliance_risk"


def correlate_alerts(
    alerts: List[KPIAlert],
    *,
    window_hours: int = 72,
) -> List[Dict[str, Any]]:
    """
    Group open alerts into incidents when multiple KPI types fire together.
    Future: persist correlation_id on kpi_alerts and notify once per incident.
    """
    if not settings.kpi_alert_correlation_enabled or len(alerts) < 2:
        return []

    now = datetime.now(timezone.utc)
    types = {a.alert_type for a in alerts}
    incidents: List[Dict[str, Any]] = []

    stress_types = {"budget_spike", "policy_surge", "sla_breach"}
    if len(types & stress_types) >= 2:
        ids = [a.id for a in alerts if a.alert_type in stress_types]
        priorities = [a.priority or a.severity or "medium" for a in alerts if a.id in ids]
        top_priority = (
            min(priorities, key=priority_sort_key) if priorities else AlertPriority.MEDIUM.value
        )
        incidents.append({
            "incident_type": INCIDENT_OPERATIONAL_STRESS,
            "alert_ids": ids,
            "alert_types": sorted(types & stress_types),
            "priority": top_priority,
            "summary": (
                "Multiple operational KPIs elevated together "
                "(spend, policy, and/or approval SLA)."
            ),
            "correlated_at": now.isoformat(),
            "window_hours": window_hours,
        })

    if "policy_surge" in types and "budget_spike" in types:
        ids = [a.id for a in alerts if a.alert_type in ("policy_surge", "budget_spike")]
        incidents.append({
            "incident_type": INCIDENT_COMPLIANCE_RISK,
            "alert_ids": ids,
            "alert_types": ["policy_surge", "budget_spike"],
            "priority": AlertPriority.HIGH.value,
            "summary": "Spend spike coincides with policy violation surge.",
            "correlated_at": now.isoformat(),
            "window_hours": window_hours,
        })

    return _dedupe_incidents(incidents)


def _dedupe_incidents(incidents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for inc in incidents:
        key = tuple(sorted(inc.get("alert_ids", [])))
        if key in seen:
            continue
        seen.add(key)
        out.append(inc)
    return out
