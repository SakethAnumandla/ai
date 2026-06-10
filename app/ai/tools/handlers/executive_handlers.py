"""Phase 7 executive intelligence tool handlers."""
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.schemas.common import SessionContext
from app.ai.schemas.tool_result import ToolResult
from app.executive.dashboard import ExecutiveDashboardService
from app.executive.efficiency import OrganizationEfficiencyService
from app.executive.financial_health import FinancialHealthService
from app.executive.insights import ExecutiveInsightService
from app.executive.operational_risk import OperationalRiskSummaryService
from app.executive.scope import can_use_tool
from app.executive.strategic_recommendations import StrategicRecommendationService
from app.models import User


def _deny(user: User, tool_name: str) -> Optional[ToolResult]:
    if not can_use_tool(user, tool_name):
        return ToolResult.fail(
            "Executive intelligence requires finance admin or super admin role.",
            error="role_denied",
        )
    return None


async def handle_executive_financial_health_v1(
    *, db: Session, user: User, ctx: SessionContext, quarters: int = 1, **_
) -> ToolResult:
    tool = "executive.financial_health.v1"
    denied = _deny(user, tool)
    if denied:
        return denied
    data = FinancialHealthService(db).summary(user, quarters=quarters)
    return ToolResult.ok(message=data.get("narrative", "Financial health summary."), data=data)


async def handle_executive_operational_risk_v1(
    *, db: Session, user: User, ctx: SessionContext, months: int = 3, **_
) -> ToolResult:
    tool = "executive.operational_risk.v1"
    denied = _deny(user, tool)
    if denied:
        return denied
    data = OperationalRiskSummaryService(db).summary(user, months=months)
    return ToolResult.ok(message=data.get("narrative", "Operational risk summary."), data=data)


async def handle_executive_kpi_summary_v1(
    *, db: Session, user: User, ctx: SessionContext, **_
) -> ToolResult:
    tool = "executive.kpi_summary.v1"
    denied = _deny(user, tool)
    if denied:
        return denied
    data = ExecutiveDashboardService(db).kpi_summary(user)
    return ToolResult.ok(message=data.get("narrative", "KPI summary."), data=data)


async def handle_executive_vendor_growth_v1(
    *, db: Session, user: User, ctx: SessionContext, limit: int = 10, **_
) -> ToolResult:
    tool = "executive.vendor_growth.v1"
    denied = _deny(user, tool)
    if denied:
        return denied
    data = ExecutiveInsightService(db).vendor_growth(user, limit=limit)
    return ToolResult.ok(message=data.get("narrative", "Vendor growth."), data=data)


async def handle_executive_department_efficiency_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    department: Optional[str] = None,
    **_,
) -> ToolResult:
    tool = "executive.department_efficiency.v1"
    denied = _deny(user, tool)
    if denied:
        return denied
    data = OrganizationEfficiencyService(db).department_efficiency(
        user, department=department
    )
    msg = data.get("primary_insight") or data.get("narrative", "Department efficiency.")
    return ToolResult.ok(message=msg, data=data)


async def handle_executive_forecast_summary_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    months: int = 6,
    department: Optional[str] = None,
    **_,
) -> ToolResult:
    tool = "executive.forecast_summary.v1"
    denied = _deny(user, tool)
    if denied:
        return denied
    data = ExecutiveInsightService(db).forecast_summary(
        user, months=months, department=department
    )
    return ToolResult.ok(message=data.get("narrative", "Forecast summary."), data=data)


async def handle_executive_executive_pack_v1(
    *, db: Session, user: User, ctx: SessionContext, quarters: int = 1, **_
) -> ToolResult:
    tool = "executive.executive_pack.v1"
    denied = _deny(user, tool)
    if denied:
        return denied
    data = ExecutiveInsightService(db).executive_pack(user, quarters=quarters)
    return ToolResult.ok(
        message=data.get("executive_summary", "Executive intelligence pack."),
        data=data,
    )


async def handle_executive_strategic_recommendations_v1(
    *, db: Session, user: User, ctx: SessionContext, **_
) -> ToolResult:
    tool = "executive.strategic_recommendations.v1"
    denied = _deny(user, tool)
    if denied:
        return denied
    data = StrategicRecommendationService(db).recommend(user)
    return ToolResult.ok(message=data.get("narrative", "Strategic recommendations."), data=data)
