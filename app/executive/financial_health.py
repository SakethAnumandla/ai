"""FinancialHealthService — executive financial health summaries."""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.executive.narratives import ExecutiveNarrativeService
from app.finance.finance_analytics import FinanceAnalyticsService
from app.finance.services import FinanceAnalyticsFacade
from app.models import User


class FinancialHealthService:
    def __init__(self, db: Session):
        self._db = db
        self._facade = FinanceAnalyticsFacade(db)
        self._finance = FinanceAnalyticsService(db)
        self._narrative = ExecutiveNarrativeService()

    def summary(
        self,
        user: User,
        *,
        quarters: int = 1,
    ) -> Dict[str, Any]:
        tenant_id = resolve_tenant_id(user)
        qtr = self._finance.quarter_comparison(user)
        trends = self._facade.spend_trends(user, tenant_id, quarters=quarters)
        policy = self._facade.policy_violations(user, tenant_id, months=3)
        health = self._facade.approval_health(user, tenant_id)

        top_cats = trends.get("top_categories") or []
        drivers = [
            c.get("category", str(c)) for c in top_cats if isinstance(c, dict)
        ]
        if not drivers and trends.get("narrative") and "Primary drivers:" in trends["narrative"]:
            tail = trends["narrative"].split("Primary drivers:")[-1].strip().rstrip(".")
            drivers = [d.strip() for d in tail.split(",")][:3]

        quarter_change = qtr.get("change_pct", trends.get("quarter_change_pct"))
        payload = {
            "quarter_change_pct": quarter_change,
            "current_quarter_spend": qtr.get("current_quarter_spend"),
            "prior_quarter_spend": qtr.get("prior_quarter_spend"),
            "total_spend": trends.get("total_spend"),
            "top_drivers": [d.strip() for d in drivers if d],
            "spend_narrative": trends.get("narrative"),
            "policy": policy,
            "approval_health": health,
            "by_month": trends.get("by_month"),
        }
        opening = self._narrative.financial_health_opening(payload)
        sla_line = self._narrative.sla_performance_line(health.get("queue", {}))
        policy_line = self._narrative.policy_trend_line(policy)

        bullets = [opening]
        if sla_line:
            bullets.append(sla_line)
        if policy_line:
            bullets.append(policy_line)

        return {
            **payload,
            "narrative": "\n".join(bullets),
            "bullets": bullets,
            "period": "quarter",
        }
