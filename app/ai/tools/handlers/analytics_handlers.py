"""Analytics tool handlers."""
from sqlalchemy.orm import Session

from app.ai.schemas.common import SessionContext
from app.ai.schemas.tool_result import ToolResult
from app.models import User, UserRole
from app.ai.services.analytics_service import AnalyticsService


async def handle_analytics_monthly_spend_v1(
    *, db: Session, user: User, ctx: SessionContext, months: int = 1, **_
) -> ToolResult:
    dept_scope = user.role in (
        UserRole.DEPARTMENT_HEAD,
        UserRole.MANAGER,
        UserRole.FINANCE_ADMIN,
        UserRole.SUPER_ADMIN,
    )
    data = AnalyticsService(db).monthly_spend(
        user=user, months=months, department_scope=dept_scope
    )
    return ToolResult.ok(
        message=f"Total spend ₹{data['total_spend']:,.2f} across {data['expense_count']} expenses.",
        data=data,
    )


async def handle_analytics_vendor_breakdown_v1(
    *, db: Session, user: User, ctx: SessionContext, limit: int = 10, **_
) -> ToolResult:
    dept_scope = user.role in (
        UserRole.MANAGER,
        UserRole.FINANCE_ADMIN,
        UserRole.SUPER_ADMIN,
    )
    data = AnalyticsService(db).vendor_breakdown(
        user=user, limit=limit, department_scope=dept_scope
    )
    top = data["vendors"][:3]
    summary = ", ".join(f"{v['vendor']} (₹{v['total']:,.0f})" for v in top) or "none"
    return ToolResult.ok(
        message=f"Top vendors: {summary}.",
        data=data,
    )
