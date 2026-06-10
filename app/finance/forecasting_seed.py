"""Forecasting seed — moving averages, MoM trends, seasonal heuristics (no ML)."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.finance.forecast_explainability import ForecastExplainabilityService
from app.finance.scope import expense_base_query, period_range
from app.models import Expense, User


class ForecastingSeedService:
    """
    Next-month spend prediction using rolling averages and simple seasonality.
    """

    def __init__(self, db: Session):
        self._db = db

    def forecast(
        self,
        user: User,
        *,
        lookback_months: int = 6,
        department: Optional[str] = None,
        main_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        start, end = period_range(months=lookback_months)
        rows = expense_base_query(
            self._db, user, start=start, end=end, department=department
        ).all()
        if main_category:
            rows = [
                e for e in rows
                if e.main_category and e.main_category.value == main_category
            ]

        by_month: Dict[str, float] = defaultdict(float)
        for e in rows:
            key = e.bill_date.strftime("%Y-%m") if e.bill_date else "unknown"
            by_month[key] += e.bill_amount

        series = sorted(by_month.items())
        if len(series) < 2:
            return {
                "enabled": True,
                "method": "insufficient_history",
                "forecasts": [],
                "message": "Need at least 2 months of history for forecast.",
            }

        values = [v for _, v in series]
        # 3-month moving average
        window = min(3, len(values))
        ma = sum(values[-window:]) / window

        # MoM trend from last two months
        mom_pct = 0.0
        if len(values) >= 2 and values[-2] > 0:
            mom_pct = (values[-1] - values[-2]) / values[-2] * 100

        # Seasonal heuristic: same month last year if available
        seasonal_note = None
        now = datetime.utcnow()
        target_key = now.strftime("%Y-%m")
        last_year_key = f"{now.year - 1}-{now.month:02d}"
        if last_year_key in by_month:
            seasonal_note = f"Same month last year: ₹{by_month[last_year_key]:,.2f}"

        predicted = ma * (1 + mom_pct / 100 * 0.5)
        band = predicted * 0.15

        next_period = (now.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")
        drivers = []
        if mom_pct > 5:
            drivers.append(f"upward MoM trend ({mom_pct:+.1f}%)")
        elif mom_pct < -5:
            drivers.append(f"downward MoM trend ({mom_pct:+.1f}%)")
        drivers.append(f"{window}-month moving average ₹{ma:,.0f}")

        by_cat_forecast = self._category_forecasts(user, lookback_months, department)
        hist = {k: round(v, 2) for k, v in series}

        result: Dict[str, Any] = {
            "enabled": True,
            "method": "moving_average_mom_seasonal",
            "lookback_months": lookback_months,
            "historical_by_month": hist,
            "forecasts": [
                {
                    "period": next_period,
                    "predicted_spend": round(predicted, 2),
                    "lower_bound": round(predicted - band, 2),
                    "upper_bound": round(predicted + band, 2),
                    "confidence": 0.55 if len(values) >= 3 else 0.4,
                    "drivers": drivers,
                    "seasonal_note": seasonal_note,
                }
            ],
            "by_category": by_cat_forecast,
            "narrative": (
                f"Forecast next month ~₹{predicted:,.0f} "
                f"(range ₹{predicted - band:,.0f}–₹{predicted + band:,.0f}). "
                + " ".join(drivers[:2])
            ),
        }

        if settings.forecast_explainability_enabled:
            explanation = ForecastExplainabilityService().explain(
                historical_by_month=hist,
                predicted=predicted,
                mom_pct=mom_pct,
                moving_average=ma,
                window=window,
                seasonal_note=seasonal_note,
                by_category=by_cat_forecast,
            )
            result["explanation"] = explanation
            if explanation.get("summary"):
                result["narrative"] = explanation["summary"]

        return result

    def _category_forecasts(
        self,
        user: User,
        months: int,
        department: Optional[str],
    ) -> List[Dict[str, Any]]:
        from app.finance.finance_analytics import FinanceAnalyticsService

        cats = FinanceAnalyticsService(self._db).category_breakdown(
            user, months=months, department=department
        )
        out = []
        for c in cats.get("categories", [])[:8]:
            out.append({
                "category": c["category"],
                "recent_monthly_avg": round(c["total"] / max(months, 1), 2),
                "share_pct": c["share_pct"],
            })
        return out
