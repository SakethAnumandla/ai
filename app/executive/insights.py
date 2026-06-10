"""ExecutiveInsightService — orchestrates Phase 7 executive intelligence."""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.executive.dashboard import ExecutiveDashboardService
from app.executive.efficiency import OrganizationEfficiencyService
from app.executive.financial_health import FinancialHealthService
from app.executive.narratives import ExecutiveNarrativeService
from app.executive.operational_risk import OperationalRiskSummaryService
from app.executive.strategic_recommendations import StrategicRecommendationService
from app.finance.forecasting_seed import ForecastingSeedService
from app.finance.services import FinanceAnalyticsFacade
from app.finance.vendor_intelligence import VendorIntelligenceService
from app.models import User


class ExecutiveInsightService:
    """Top-level executive intelligence — board packs and cross-domain summaries."""

    def __init__(self, db: Session):
        self._db = db
        self._health = FinancialHealthService(db)
        self._risk = OperationalRiskSummaryService(db)
        self._dashboard = ExecutiveDashboardService(db)
        self._efficiency = OrganizationEfficiencyService(db)
        self._strategic = StrategicRecommendationService(db)
        self._facade = FinanceAnalyticsFacade(db)
        self._forecast = ForecastingSeedService(db)
        self._vendors = VendorIntelligenceService(db)
        self._narrative = ExecutiveNarrativeService()

    def executive_pack(self, user: User, *, quarters: int = 1) -> Dict[str, Any]:
        tenant_id = resolve_tenant_id(user)
        health = self._health.summary(user, quarters=quarters)
        risks = self._risk.summary(user)
        kpis = self._dashboard.kpi_summary(user)
        efficiency = self._efficiency.score(user)
        recommendations = self._strategic.recommend(user)
        vendor_growth = self.vendor_growth(user)
        forecast = self.forecast_summary(user)

        summary = self._narrative.compose_executive_summary({
            "financial": health.get("narrative", ""),
            "risks": risks.get("narrative", ""),
            "efficiency": efficiency.get("narrative", ""),
            "outlook": forecast.get("narrative", ""),
        })

        return {
            "executive_summary": summary,
            "financial_health": health,
            "operational_risks": risks,
            "kpi_summary": kpis,
            "efficiency": efficiency,
            "vendor_growth": vendor_growth,
            "forecast": forecast,
            "strategic_recommendations": recommendations,
            "tenant_id": tenant_id,
            "period_quarters": quarters,
        }

    def vendor_growth(self, user: User, *, limit: int = 10) -> Dict[str, Any]:
        growth_data = self._vendors.vendor_growth(user, limit=limit)
        tenant_id = resolve_tenant_id(user)
        top = self._facade.top_vendors(user, tenant_id, limit=1, months=3)
        top_vendor = None
        if top.get("vendors"):
            top_vendor = top["vendors"][0].get("vendor")

        growth_list = growth_data.get("vendor_growth", [])
        lines = self._narrative.vendor_growth_lines(growth_list, top_volume=top_vendor)
        narrative = "\n".join(lines) if lines else "No significant vendor growth this period."

        return {
            **growth_data,
            "highest_volume_vendor": top_vendor,
            "narrative": narrative,
            "bullets": lines,
        }

    def forecast_summary(
        self,
        user: User,
        *,
        months: int = 6,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        tenant_id = resolve_tenant_id(user)
        data = self._facade.forecast(
            user, tenant_id, lookback_months=months, department=department
        )
        narrative = data.get("narrative", "")
        if data.get("explanation", {}).get("summary"):
            narrative = data["explanation"]["summary"]
        forecasts = data.get("forecasts") or []
        outlook = ""
        if forecasts:
            f0 = forecasts[0]
            outlook = (
                f"Next month ({f0.get('period')}): predicted spend "
                f"₹{f0.get('predicted_spend', 0):,.0f} "
                f"(range ₹{f0.get('lower_bound', 0):,.0f}–₹{f0.get('upper_bound', 0):,.0f})."
            )
        return {
            **data,
            "outlook_line": outlook,
            "narrative": narrative or outlook,
            "predictive_note": "Heuristic forecast for operational planning — not ML.",
        }
