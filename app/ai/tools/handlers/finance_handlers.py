"""Phase 6 finance analytics tool handlers (cached facade)."""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.ai.schemas.common import SessionContext
from app.ai.schemas.tool_result import ToolResult
from app.ai.security import resolve_tenant_id
from app.finance.reimbursement_ageing import ReimbursementAgeingService
from app.finance.services import FinanceAnalyticsFacade
from app.manager.analytics import ManagerAnalyticsService
from app.models import User, UserRole


def _finance_roles(user: User) -> bool:
    return user.role in (
        UserRole.FINANCE_ADMIN,
        UserRole.SUPER_ADMIN,
        UserRole.MANAGER,
        UserRole.DEPARTMENT_HEAD,
    )


def _deny(user: User) -> Optional[ToolResult]:
    if not _finance_roles(user):
        return ToolResult.fail("Finance or manager role required.", error="role_denied")
    return None


def _facade(db: Session) -> FinanceAnalyticsFacade:
    return FinanceAnalyticsFacade(db)


async def handle_analytics_monthly_spend_v1(
    *, db: Session, user: User, ctx: SessionContext, months: int = 3, **_
) -> ToolResult:
    denied = _deny(user)
    if denied:
        return denied
    tenant_id = resolve_tenant_id(user)
    data = _facade(db).spend_trends(
        user, tenant_id, quarters=max(1, months // 3 or 1)
    )
    msg = data.get("narrative") or f"Total spend ₹{data.get('total_spend', 0):,.2f}."
    return ToolResult.ok(message=msg, data=data)


async def handle_analytics_department_trends_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    months: int = 6,
    department: Optional[str] = None,
    **_,
) -> ToolResult:
    denied = _deny(user)
    if denied:
        return denied
    tenant_id = resolve_tenant_id(user)
    data = _facade(db).department_trends(
        user, tenant_id, months=months, department=department
    )
    return ToolResult.ok(
        message=f"Department trends over {months} month(s).",
        data=data,
    )


async def handle_analytics_category_breakdown_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    months: int = 1,
    department: Optional[str] = None,
    **_,
) -> ToolResult:
    denied = _deny(user)
    if denied:
        return denied
    tenant_id = resolve_tenant_id(user)
    data = _facade(db).category_breakdown(
        user, tenant_id, months=months, department=department
    )
    top = data.get("categories", [])[:3]
    names = ", ".join(f"{c['category']} ({c['share_pct']}%)" for c in top)
    return ToolResult.ok(
        message=f"Spend by category: {names}." if names else "No category spend.",
        data=data,
    )


async def handle_analytics_vendor_breakdown_v1(
    *, db: Session, user: User, ctx: SessionContext, limit: int = 10, months: int = 1, **_
) -> ToolResult:
    denied = _deny(user)
    if denied:
        return denied
    tenant_id = resolve_tenant_id(user)
    data = _facade(db).top_vendors(user, tenant_id, limit=limit, months=months)
    return ToolResult.ok(message=data.get("narrative", "Vendor breakdown."), data=data)


async def handle_analytics_policy_violations_v1(
    *, db: Session, user: User, ctx: SessionContext, months: int = 3, **_
) -> ToolResult:
    denied = _deny(user)
    if denied:
        return denied
    tenant_id = resolve_tenant_id(user)
    data = _facade(db).policy_violations(user, tenant_id, months=months)
    return ToolResult.ok(
        message=data.get("narrative") or f"{data['violation_count']} policy violations found.",
        data=data,
    )


async def handle_analytics_approval_delays_v1(
    *, db: Session, user: User, ctx: SessionContext, **_
) -> ToolResult:
    denied = _deny(user)
    if denied:
        return denied

    if user.role in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN):
        tenant_id = resolve_tenant_id(user)
        data = _facade(db).approval_health(user, tenant_id)
        sla = data.get("sla_at_risk", {})
        return ToolResult.ok(
            message=sla.get("narrative", "Approval delay analytics."),
            data=data,
        )

    data = ManagerAnalyticsService(db).approval_delays(user.id)
    return ToolResult.ok(
        message=(
            f"Average wait {data['average_hours_waiting']}h across "
            f"{data['pending_count']} pending."
        ),
        data=data,
    )


async def handle_analytics_reimbursements_v1(
    *, db: Session, user: User, ctx: SessionContext, **_
) -> ToolResult:
    denied = _deny(user)
    if denied:
        return denied
    data = ReimbursementAgeingService(db).ageing_report(user)
    return ToolResult.ok(
        message=data.get("narrative", "Reimbursement ageing report."),
        data=data,
    )


async def handle_analytics_forecast_seed_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    months: int = 6,
    department: Optional[str] = None,
    main_category: Optional[str] = None,
    **_,
) -> ToolResult:
    denied = _deny(user)
    if denied:
        return denied
    tenant_id = resolve_tenant_id(user)
    data = _facade(db).forecast(
        user,
        tenant_id,
        lookback_months=months,
        department=department,
        main_category=main_category,
    )
    msg = data.get("narrative", "Spend forecast.")
    if data.get("explanation", {}).get("summary"):
        msg = data["explanation"]["summary"]
    return ToolResult.ok(message=msg, data=data)
