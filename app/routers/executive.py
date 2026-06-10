"""Phase 7 — Executive intelligence REST API."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.executive.dashboard import ExecutiveDashboardService
from app.executive.efficiency import OrganizationEfficiencyService
from app.executive.financial_health import FinancialHealthService
from app.executive.insights import ExecutiveInsightService
from app.executive.operational_risk import OperationalRiskSummaryService
from app.executive.scope import is_full_executive
from app.executive.strategic_recommendations import StrategicRecommendationService
from app.models import User

router = APIRouter(prefix="/executive", tags=["executive"])


def _require_executive(user: User) -> None:
    if not is_full_executive(user):
        raise HTTPException(
            status_code=403,
            detail="Executive intelligence requires finance admin or super admin",
        )


@router.get("/financial-health")
def financial_health(
    quarters: int = Query(1, ge=1, le=4),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_executive(user)
    return FinancialHealthService(db).summary(user, quarters=quarters)


@router.get("/operational-risks")
def operational_risks(
    months: int = Query(3, ge=1, le=12),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_executive(user)
    return OperationalRiskSummaryService(db).summary(user, months=months)


@router.get("/kpi-summary")
def kpi_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_executive(user)
    return ExecutiveDashboardService(db).kpi_summary(user)


@router.get("/vendor-growth")
def vendor_growth(
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_executive(user)
    return ExecutiveInsightService(db).vendor_growth(user, limit=limit)


@router.get("/efficiency")
def organization_efficiency(
    department: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_full_executive(user) and not user.department:
        raise HTTPException(status_code=403, detail="Executive or department scope required")
    svc = OrganizationEfficiencyService(db)
    if department or not is_full_executive(user):
        return svc.department_efficiency(user, department=department)
    return svc.score(user)


@router.get("/forecast-summary")
def forecast_summary(
    months: int = Query(6, ge=2, le=24),
    department: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_executive(user)
    return ExecutiveInsightService(db).forecast_summary(
        user, months=months, department=department
    )


@router.get("/strategic-recommendations")
def strategic_recommendations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_executive(user)
    return StrategicRecommendationService(db).recommend(user)


@router.get("/dashboard")
def executive_dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_executive(user)
    return ExecutiveDashboardService(db).dashboard(user)


@router.get("/pack")
def executive_pack(
    quarters: int = Query(1, ge=1, le=4),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_executive(user)
    return ExecutiveInsightService(db).executive_pack(user, quarters=quarters)
