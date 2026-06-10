"""ExecutiveDashboardService — board-level KPI dashboard."""
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.executive.financial_health import FinancialHealthService
from app.executive.narratives import ExecutiveNarrativeService
from app.executive.operational_risk import OperationalRiskSummaryService
from app.finance.kpi_alerts import KPIAlertService
from app.finance.services import FinanceAnalyticsFacade
from app.models import User


class ExecutiveDashboardService:
    def __init__(self, db: Session):
        self._db = db
        self._facade = FinanceAnalyticsFacade(db)
        self._health = FinancialHealthService(db)
        self._risk = OperationalRiskSummaryService(db)
        self._kpi = KPIAlertService(db)
        self._narrative = ExecutiveNarrativeService()

    def dashboard(self, user: User) -> Dict[str, Any]:
        tenant_id = resolve_tenant_id(user)
        health = self._health.summary(user)
        risks = self._risk.summary(user)
        forecast = self._facade.forecast(user, tenant_id, lookback_months=6)
        vendors = self._facade.top_vendors(user, tenant_id, limit=5, months=1)
        alerts = self._kpi.list_alerts(tenant_id, status="open", limit=10)

        kpis: List[Dict[str, Any]] = [
            {
                "key": "quarter_spend_change",
                "label": "Quarter spend change",
                "value": f"{health.get('quarter_change_pct', 0):+.1f}%",
                "status": "warning" if abs(health.get("quarter_change_pct") or 0) > 15 else "ok",
            },
            {
                "key": "open_risks",
                "label": "Operational risks",
                "value": str(risks.get("risk_count", 0)),
                "status": "warning" if risks.get("risk_count", 0) >= 3 else "ok",
            },
            {
                "key": "open_alerts",
                "label": "Open KPI alerts",
                "value": str(len(alerts)),
                "status": "critical" if any(
                    a.priority == "critical" for a in alerts
                ) else "ok",
            },
            {
                "key": "forecast_next_month",
                "label": "Next-month forecast",
                "value": self._forecast_label(forecast),
                "status": "info",
            },
            {
                "key": "top_vendor_concentration",
                "label": "Top-3 vendor share",
                "value": f"{vendors.get('top3_concentration_pct', 0):.0f}%",
                "status": "warning" if (vendors.get("top3_concentration_pct") or 0) > 50 else "ok",
            },
        ]

        return {
            "kpis": kpis,
            "financial_health": health,
            "operational_risks": risks,
            "narrative": self._narrative.kpi_summary_paragraph(kpis),
            "generated_at": health.get("period"),
        }

    def kpi_summary(self, user: User) -> Dict[str, Any]:
        data = self.dashboard(user)
        return {
            "kpis": data["kpis"],
            "narrative": data["narrative"],
            "bullets": [f"{k['label']}: {k['value']}" for k in data["kpis"]],
        }

    def _forecast_label(self, forecast: Dict[str, Any]) -> str:
        forecasts = forecast.get("forecasts") or []
        if not forecasts:
            return "N/A"
        pred = forecasts[0].get("predicted_spend", 0)
        return f"₹{pred:,.0f}"
