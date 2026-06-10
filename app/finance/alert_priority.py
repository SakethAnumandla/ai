"""KPI alert priority tiers — critical, high, medium, low."""
from enum import Enum
from typing import Any, Dict, Optional

from app.config import settings


class AlertPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


PRIORITY_RANK = {
    AlertPriority.CRITICAL: 0,
    AlertPriority.HIGH: 1,
    AlertPriority.MEDIUM: 2,
    AlertPriority.LOW: 3,
}


def resolve_priority(
    alert_type: str,
    *,
    severity: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Map alert signals to a four-tier priority.
    `severity` is kept for backward compatibility; `priority` is canonical for sorting/UI.
    """
    details = details or {}
    if alert_type == "budget_spike":
        pct = float(details.get("mom_pct") or 0)
        threshold = settings.kpi_alert_budget_spike_pct
        if pct >= threshold * 2:
            return AlertPriority.CRITICAL.value
        if pct >= threshold:
            return AlertPriority.HIGH.value
        return AlertPriority.MEDIUM.value

    if alert_type == "policy_surge":
        count = int(details.get("violation_count") or 0)
        threshold = settings.kpi_alert_policy_surge_count
        if count >= threshold * 2:
            return AlertPriority.CRITICAL.value
        if count >= threshold:
            return AlertPriority.HIGH.value
        return AlertPriority.MEDIUM.value

    if alert_type == "sla_breach":
        overdue_pct = float(details.get("overdue_pct") or 0)
        queue = details.get("queue_health", "")
        if queue == "critical" or overdue_pct >= settings.kpi_alert_sla_overdue_pct * 2:
            return AlertPriority.CRITICAL.value
        if overdue_pct >= settings.kpi_alert_sla_overdue_pct:
            return AlertPriority.HIGH.value
        return AlertPriority.MEDIUM.value

    # Fallback from legacy severity string
    if severity == "critical":
        return AlertPriority.CRITICAL.value
    if severity == "high":
        return AlertPriority.HIGH.value
    if severity == "low":
        return AlertPriority.LOW.value
    return AlertPriority.MEDIUM.value


def priority_sort_key(priority: str) -> int:
    try:
        return PRIORITY_RANK[AlertPriority(priority)]
    except ValueError:
        return PRIORITY_RANK[AlertPriority.MEDIUM]
