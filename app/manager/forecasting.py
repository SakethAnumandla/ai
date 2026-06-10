"""Spend forecasting — Phase 6+ extension point (not enabled in production)."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import User


@dataclass
class ForecastPoint:
    period: str
    category: Optional[str]
    predicted_spend: float
    lower_bound: float
    upper_bound: float
    confidence: float
    drivers: List[str]


class SpendForecastingEngine:
    """
    Next-month spend prediction and future budget/vendor/reimbursement forecasts.

    MVP (future): rolling 3-month average by category.
    Phase 6+: seasonal adjustment, tenant-specific models.
    """

    def __init__(self, db: Session):
        self._db = db

    def forecast_next_month(
        self,
        *,
        tenant_id: int,
        department: Optional[str] = None,
        main_category: Optional[str] = None,
        lookback_months: int = 6,
    ) -> Dict[str, Any]:
        from app.config import settings

        if not getattr(settings, "forecasting_enabled", False):
            return {
                "enabled": False,
                "message": "Forecasting is not enabled. Set FORECASTING_ENABLED=true when Phase 6 ships.",
                "forecasts": [],
            }

        # Future: query Expense/Claim aggregates, compute rolling mean + bands
        return {
            "enabled": True,
            "period": datetime.utcnow().strftime("%Y-%m"),
            "forecasts": [],
            "note": "Implement rolling-average forecaster in Phase 6.",
        }

    def forecast_reimbursement_pipeline(
        self, tenant_id: int, *, department: Optional[str] = None
    ) -> Dict[str, Any]:
        return {"enabled": False, "predicted_reimbursements": [], "note": "Phase 6+"}

    def forecast_vendor_trends(
        self, tenant_id: int, *, limit: int = 10
    ) -> Dict[str, Any]:
        return {"enabled": False, "vendors": [], "note": "Phase 6+"}


def get_forecasting_engine(db: Session) -> SpendForecastingEngine:
    return SpendForecastingEngine(db)
