"""Manager copilot REST endpoints — bulk preview exports, simulation."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.manager.bulk_planner import BulkApprovalPlanner
from app.manager.dry_run_export import BulkDryRunExporter
from app.manager.schemas import BulkApprovalFilters
from app.manager.simulation import ApprovalSimulationService
from app.ai.security import resolve_tenant_id
from app.finance.forecasting_seed import ForecastingSeedService
from app.manager.policy_impact import PolicyImpactAnalyticsService
from app.manager.sla_prediction import SLABreachPredictor
from app.manager.workload_analytics import ManagerWorkloadAnalyticsService
from app.models import User, UserRole

router = APIRouter(prefix="/manager", tags=["manager"])


def _require_manager(user: User) -> None:
    if user.role not in (
        UserRole.MANAGER,
        UserRole.DEPARTMENT_HEAD,
        UserRole.FINANCE_ADMIN,
        UserRole.SUPER_ADMIN,
    ):
        raise HTTPException(status_code=403, detail="Manager or finance role required")


@router.get("/bulk-preview/{export_id}/download")
def download_bulk_preview(
    export_id: str,
    format: Literal["csv", "html", "pdf"] = Query("csv", alias="format"),
    user: User = Depends(get_current_user),
):
    """Download dry-run CSV or printable HTML (use Print → PDF for pdf format)."""
    _require_manager(user)
    result = BulkDryRunExporter().read_export(user.id, export_id, format)
    if not result:
        raise HTTPException(status_code=404, detail="Export not found or expired")
    content, media_type, filename = result
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/bulk-preview/export")
def create_bulk_preview_export(
    filters: BulkApprovalFilters,
    export_format: Literal["csv", "html", "pdf"] = "csv",
    include_simulation: bool = True,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate exportable bulk approval dry-run without executing."""
    _require_manager(user)
    preview = BulkApprovalPlanner(db).preview(
        user,
        filters,
        include_export=True,
        export_format=export_format,
        include_simulation=include_simulation,
    )
    return preview.model_dump(mode="json")


@router.post("/approvals/simulate")
def simulate_approvals(
    filters: Optional[BulkApprovalFilters] = None,
    approval_ids: Optional[list[int]] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Simulate policy/budget impact if claims are approved (no mutations)."""
    _require_manager(user)
    result = ApprovalSimulationService(db).simulate_bulk_approve(
        user,
        filters=filters,
        approval_ids=approval_ids,
    )
    return result.model_dump(mode="json")


@router.get("/analytics/workload-delays")
def manager_workload_delays(
    days: int = Query(30, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 6 foundation: managers with slowest approval times."""
    _require_manager(user)
    if user.role not in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Finance role required")
    return ManagerWorkloadAnalyticsService(db).manager_delay_leaderboard(days=days)


@router.get("/analytics/policy-impact")
def policy_impact_analytics(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Which policies drive escalations and rejections (Phase 6 analytics foundation)."""
    _require_manager(user)
    if user.role not in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=403, detail="Not authorized")
    return PolicyImpactAnalyticsService(db).summarize(
        tenant_id=resolve_tenant_id(user),
        limit=limit,
    )


@router.get("/approvals/sla-at-risk")
def approvals_sla_at_risk(
    limit: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pending approvals likely to breach SLA."""
    _require_manager(user)
    preds = SLABreachPredictor(db).predict_at_risk(user, limit=limit)
    return {
        "at_risk": [p.model_dump(mode="json") for p in preds],
        "count": len(preds),
    }


@router.get("/analytics/forecast")
def spend_forecast_stub(
    main_category: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Next-month spend forecast (Phase 6+ — disabled until FORECASTING_ENABLED)."""
    _require_manager(user)
    return ForecastingSeedService(db).forecast(
        user,
        lookback_months=6,
        department=user.department.value if user.department else None,
        main_category=main_category,
    )
