"""Forecast explainability — structured reasons for predicted spend changes."""
from typing import Any, Dict, List, Optional


class ForecastExplainabilityService:
    """
    Builds human-readable and structured explanations from forecast seed output.
    Phase 7+ may swap in ML feature attributions; this layer stays stable.
    """

    def explain(
        self,
        *,
        historical_by_month: Dict[str, float],
        predicted: float,
        mom_pct: float,
        moving_average: float,
        window: int,
        seasonal_note: Optional[str] = None,
        by_category: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        factors: List[Dict[str, Any]] = []
        direction = "flat"

        if mom_pct > 5:
            direction = "increase"
            factors.append({
                "factor": "mom_trend",
                "impact": "increase",
                "weight": min(abs(mom_pct) / 100, 0.5),
                "detail": f"Recent month-over-month trend is +{mom_pct:.1f}%, lifting the baseline.",
            })
        elif mom_pct < -5:
            direction = "decrease"
            factors.append({
                "factor": "mom_trend",
                "impact": "decrease",
                "weight": min(abs(mom_pct) / 100, 0.5),
                "detail": f"Recent month-over-month trend is {mom_pct:.1f}%, pulling the forecast down.",
            })

        if moving_average > 0:
            last_val = list(historical_by_month.values())[-1] if historical_by_month else 0
            if predicted > last_val * 1.03:
                factors.append({
                    "factor": "moving_average",
                    "impact": "increase",
                    "weight": 0.35,
                    "detail": (
                        f"{window}-month moving average (₹{moving_average:,.0f}) "
                        "smooths history upward versus the latest month."
                    ),
                })
            elif predicted < last_val * 0.97:
                factors.append({
                    "factor": "moving_average",
                    "impact": "decrease",
                    "weight": 0.35,
                    "detail": (
                        f"{window}-month moving average (₹{moving_average:,.0f}) "
                        "anchors the forecast below recent spend."
                    ),
                })

        if seasonal_note:
            factors.append({
                "factor": "seasonality",
                "impact": "neutral",
                "weight": 0.15,
                "detail": seasonal_note,
            })

        top_cat = None
        if by_category:
            top_cat = max(by_category, key=lambda c: c.get("share_pct", 0), default=None)
            if top_cat and top_cat.get("share_pct", 0) >= 20:
                factors.append({
                    "factor": "category_concentration",
                    "impact": "increase" if direction == "increase" else "neutral",
                    "weight": 0.2,
                    "detail": (
                        f"{top_cat.get('category', 'category')} represents "
                        f"{top_cat.get('share_pct', 0):.0f}% of spend."
                    ),
                })

        summary = self._build_summary(direction, factors, predicted)
        return {
            "direction": direction,
            "summary": summary,
            "factors": factors,
            "confidence_note": (
                "Heuristic seed forecast — not ML. Use for directional planning only."
            ),
        }

    def _build_summary(
        self,
        direction: str,
        factors: List[Dict[str, Any]],
        predicted: float,
    ) -> str:
        if not factors:
            return f"Forecast ~₹{predicted:,.0f} with limited historical signal."
        increase = [f for f in factors if f.get("impact") == "increase"]
        if direction == "increase" and increase:
            primary = increase[0]["detail"]
            return f"Forecast predicts an increase (~₹{predicted:,.0f}) mainly because {primary}"
        decrease = [f for f in factors if f.get("impact") == "decrease"]
        if direction == "decrease" and decrease:
            primary = decrease[0]["detail"]
            return f"Forecast predicts lower spend (~₹{predicted:,.0f}) because {primary}"
        return f"Forecast ~₹{predicted:,.0f} based on blended historical patterns."
