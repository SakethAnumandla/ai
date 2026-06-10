"""Cached finance analytics facade."""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.finance.approval_delays import ApprovalDelayAnalyticsService
from app.finance.cache import AnalyticsCache
from app.finance.finance_analytics import FinanceAnalyticsService
from app.finance.forecasting_seed import ForecastingSeedService
from app.finance.policy_violations import PolicyViolationAnalyticsService
from app.finance.vendor_intelligence import VendorIntelligenceService
from app.models import User


class FinanceAnalyticsFacade:
    """Single entry for cached finance analytics."""

    def __init__(self, db: Session, cache: Optional[AnalyticsCache] = None):
        self._db = db
        self._cache = cache or AnalyticsCache()
        self._finance = FinanceAnalyticsService(db)
        self._vendors = VendorIntelligenceService(db)
        self._policy = PolicyViolationAnalyticsService(db)
        self._delays = ApprovalDelayAnalyticsService(db)
        self._forecast = ForecastingSeedService(db)

    def spend_trends(
        self,
        user: User,
        tenant_id: int,
        *,
        quarters: int = 1,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {"quarters": quarters, "department": department}
        return self._cache.get_or_compute(
            "spend_trends",
            tenant_id=tenant_id,
            user=user,
            params=params,
            compute_fn=lambda: self._finance.spend_trends(
                user, quarters=quarters, department=department
            ),
        )

    def category_breakdown(
        self,
        user: User,
        tenant_id: int,
        *,
        months: int = 1,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {"months": months, "department": department}
        return self._cache.get_or_compute(
            "category_breakdown",
            tenant_id=tenant_id,
            user=user,
            params=params,
            compute_fn=lambda: self._finance.category_breakdown(
                user, months=months, department=department
            ),
        )

    def department_analysis(self, user: User, tenant_id: int, *, months: int = 3) -> Dict[str, Any]:
        params = {"months": months}
        return self._cache.get_or_compute(
            "department_analysis",
            tenant_id=tenant_id,
            user=user,
            params=params,
            compute_fn=lambda: self._finance.department_analysis(user, months=months),
        )

    def department_trends(
        self,
        user: User,
        tenant_id: int,
        *,
        months: int = 6,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {"months": months, "department": department}
        return self._cache.get_or_compute(
            "department_trends",
            tenant_id=tenant_id,
            user=user,
            params=params,
            compute_fn=lambda: self._finance.department_trends(
                user, months=months, department=department
            ),
        )

    def top_vendors(
        self,
        user: User,
        tenant_id: int,
        *,
        limit: int = 10,
        months: int = 1,
    ) -> Dict[str, Any]:
        params = {"limit": limit, "months": months}
        return self._cache.get_or_compute(
            "vendor_breakdown",
            tenant_id=tenant_id,
            user=user,
            params=params,
            compute_fn=lambda: self._vendors.top_vendors(user, limit=limit, months=months),
        )

    def policy_violations(self, user: User, tenant_id: int, *, months: int = 3) -> Dict[str, Any]:
        params = {"months": months}
        return self._cache.get_or_compute(
            "policy_violations",
            tenant_id=tenant_id,
            user=user,
            params=params,
            compute_fn=lambda: self._policy.violation_summary(user, months=months),
        )

    def approval_health(self, user: User, tenant_id: int) -> Dict[str, Any]:
        return self._cache.get_or_compute(
            "approval_health",
            tenant_id=tenant_id,
            user=user,
            params={},
            compute_fn=lambda: {
                "queue": self._delays.company_queue_health(),
                "sla_at_risk": self._delays.sla_at_risk_summary(within_hours=24),
            },
        )

    def forecast(
        self,
        user: User,
        tenant_id: int,
        *,
        lookback_months: int = 6,
        department: Optional[str] = None,
        main_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {
            "months": lookback_months,
            "department": department,
            "main_category": main_category,
        }
        return self._cache.get_or_compute(
            "forecast",
            tenant_id=tenant_id,
            user=user,
            params=params,
            compute_fn=lambda: self._forecast.forecast(
                user,
                lookback_months=lookback_months,
                department=department,
                main_category=main_category,
            ),
        )
