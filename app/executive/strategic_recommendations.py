"""StrategicRecommendationService — actionable executive recommendations."""
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.executive.financial_health import FinancialHealthService
from app.executive.operational_risk import OperationalRiskSummaryService
from app.executive.efficiency import OrganizationEfficiencyService
from app.finance.vendor_intelligence import VendorIntelligenceService
from app.models import User


class StrategicRecommendationService:
    def __init__(self, db: Session):
        self._db = db
        self._health = FinancialHealthService(db)
        self._risk = OperationalRiskSummaryService(db)
        self._efficiency = OrganizationEfficiencyService(db)
        self._vendors = VendorIntelligenceService(db)

    def recommend(self, user: User) -> Dict[str, Any]:
        health = self._health.summary(user)
        risks = self._risk.summary(user)
        efficiency = self._efficiency.score(user)
        concentration = self._vendors.spend_concentration(user, months=3)

        recommendations: List[Dict[str, Any]] = []

        qtr_pct = health.get("quarter_change_pct") or 0
        if qtr_pct > 10:
            drivers = health.get("top_drivers") or []
            recommendations.append({
                "priority": "high",
                "area": "spend_governance",
                "title": "Review elevated spend drivers",
                "recommendation": (
                    f"Quarter spend is up {qtr_pct:.0f}%. Prioritize review of "
                    f"{', '.join(drivers[:2]) or 'top categories'} with department heads."
                ),
            })

        if risks.get("risk_count", 0) >= 3:
            recommendations.append({
                "priority": "high",
                "area": "operational_risk",
                "title": "Address clustered operational risks",
                "recommendation": (
                    "Multiple risk signals are active. Schedule a cross-functional "
                    "review of reimbursements, approvals, and policy compliance."
                ),
            })

        if efficiency.get("efficiency_score", 100) < 70:
            bn = efficiency.get("top_bottlenecks") or []
            dept = bn[0].get("department", "operations") if bn else "operations"
            recommendations.append({
                "priority": "medium",
                "area": "workflow",
                "title": "Reduce approval and reimbursement friction",
                "recommendation": (
                    f"Efficiency score is {efficiency.get('efficiency_score')}/100. "
                    f"Focus on {dept.title()} workflow bottlenecks first."
                ),
            })

        hhi = concentration.get("herfindahl_index", 0)
        if hhi > 0.25:
            recommendations.append({
                "priority": "medium",
                "area": "vendor_management",
                "title": "Mitigate vendor concentration",
                "recommendation": (
                    "Vendor spend is highly concentrated. Evaluate contracts and "
                    "alternate suppliers for top vendors."
                ),
            })

        policy = health.get("policy") or {}
        if policy.get("violation_count", 0) > 5:
            recommendations.append({
                "priority": "medium",
                "area": "policy",
                "title": "Policy compliance initiative",
                "recommendation": (
                    f"{policy['violation_count']} violations this period. "
                    "Run targeted training for departments with highest violation share."
                ),
            })

        if not recommendations:
            recommendations.append({
                "priority": "low",
                "area": "monitoring",
                "title": "Maintain current controls",
                "recommendation": (
                    "No critical strategic actions required. Continue monthly executive "
                    "snapshots and KPI monitoring."
                ),
            })

        recommendations.sort(
            key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r.get("priority", "low"), 2)
        )
        narrative = recommendations[0]["recommendation"] if recommendations else ""

        return {
            "recommendations": recommendations,
            "count": len(recommendations),
            "narrative": narrative,
        }
