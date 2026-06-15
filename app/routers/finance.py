"""Phase 6 finance analytics REST API + pre-Phase 7 platform endpoints."""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.finance.kpi_alerts import KPIAlertService
from app.finance.report_audit import ReportAccessAuditService
from app.finance.report_versions import list_report_versions, resolve_report_spec
from app.finance.reimbursement_ageing import ReimbursementAgeingService
from app.finance.services import FinanceAnalyticsFacade
from app.finance.snapshot_immutability import ImmutableSnapshotError
from app.finance.snapshots import AnalyticsSnapshotService
from app.intelligence.jobs.service import JobService
from app.intelligence.schemas import JobStatus, JobType, ProcessingJobOut
from app.models import User, UserRole

router = APIRouter(prefix="/finance", tags=["finance"])


def _require_finance(user: User) -> None:
    if user.role not in (
        UserRole.FINANCE_ADMIN,
        UserRole.SUPER_ADMIN,
        UserRole.MANAGER,
        UserRole.DEPARTMENT_HEAD,
    ):
        raise HTTPException(status_code=403, detail="Finance or manager role required")


def _facade(db: Session) -> FinanceAnalyticsFacade:
    return FinanceAnalyticsFacade(db)


class AsyncReportRequest(BaseModel):
    report_type: str = Field(
        default="executive_pack",
        description="spend_trends | vendor_breakdown | department_analysis | executive_pack",
    )
    report_version: Optional[str] = Field(
        default=None,
        description="e.g. executive_pack_v1 — overrides report_type when set",
    )
    format: str = Field(default="csv", description="csv | json | both")
    months: int = Field(default=3, ge=1, le=24)
    quarters: int = Field(default=1, ge=1, le=4)
    department: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)


class SnapshotCaptureRequest(BaseModel):
    snapshot_type: str = Field(
        default="spend_trends",
        description="spend_trends | vendor_breakdown | department_analysis | ...",
    )
    period_label: Optional[str] = None
    department: Optional[str] = None
    months: int = Field(default=3, ge=1, le=12)
    quarters: int = Field(default=1, ge=1, le=4)
    immutable: bool = Field(default=True, description="Seal snapshot; blocks retroactive edits")
    executive: bool = Field(default=False, description="Mark as executive reporting record")


@router.get("/analytics/spend-trends")
def spend_trends(
    quarters: int = Query(1, ge=1, le=4),
    department: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    return _facade(db).spend_trends(user, tenant_id, quarters=quarters, department=department)


@router.get("/analytics/categories")
def category_breakdown(
    months: int = Query(1, ge=1, le=12),
    department: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    return _facade(db).category_breakdown(
        user, tenant_id, months=months, department=department
    )


@router.get("/analytics/departments")
def department_analysis(
    months: int = Query(3, ge=1, le=12),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    return _facade(db).department_analysis(user, tenant_id, months=months)


@router.get("/analytics/vendors")
def vendor_intelligence(
    limit: int = Query(10, ge=1, le=50),
    months: int = Query(1, ge=1, le=12),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    return _facade(db).top_vendors(user, tenant_id, limit=limit, months=months)


@router.get("/analytics/policy-violations")
def policy_violations(
    months: int = Query(3, ge=1, le=12),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    return _facade(db).policy_violations(user, tenant_id, months=months)


@router.get("/analytics/approval-health")
def approval_health(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    return _facade(db).approval_health(user, tenant_id)


@router.get("/analytics/reimbursements")
def reimbursement_ageing(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    return ReimbursementAgeingService(db).ageing_report(user)


@router.get("/analytics/forecast")
def spend_forecast(
    months: int = Query(6, ge=2, le=24),
    department: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    return _facade(db).forecast(user, tenant_id, lookback_months=months, department=department)


# --- Pre-Phase 7: snapshots ---


@router.post("/snapshots/capture")
def capture_snapshot(
    body: SnapshotCaptureRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    row = AnalyticsSnapshotService(db).capture(
        user,
        body.snapshot_type,
        period_label=body.period_label,
        department=body.department,
        months=body.months,
        quarters=body.quarters,
        immutable=body.immutable,
        executive=body.executive,
    )
    return {
        "id": row.id,
        "snapshot_type": row.snapshot_type,
        "period_label": row.period_label,
        "created_at": row.created_at,
        "summary_text": row.summary_text,
        "immutable": row.immutable,
        "content_hash": row.content_hash,
        "frozen_at": row.frozen_at,
    }


@router.post("/snapshots/executive-pack")
def capture_executive_pack(
    period_label: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    return AnalyticsSnapshotService(db).capture_executive_pack(user, period_label=period_label)


@router.get("/snapshots/compare")
def compare_snapshots(
    snapshot_a: int = Query(..., alias="a"),
    snapshot_b: int = Query(..., alias="b"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    try:
        return AnalyticsSnapshotService(db).compare(tenant_id, snapshot_a, snapshot_b)
    except ImmutableSnapshotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(
    snapshot_id: int,
    include_payload: bool = Query(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    try:
        return AnalyticsSnapshotService(db).get_snapshot(
            tenant_id, snapshot_id, include_payload=include_payload
        )
    except ImmutableSnapshotError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/snapshots")
def list_snapshots(
    snapshot_type: Optional[str] = None,
    executive_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    rows = AnalyticsSnapshotService(db).list_snapshots(
        tenant_id,
        snapshot_type=snapshot_type,
        executive_only=executive_only,
        limit=limit,
    )
    return [
        {
            "id": r.id,
            "snapshot_type": r.snapshot_type,
            "period_label": r.period_label,
            "department": r.department,
            "summary_text": r.summary_text,
            "immutable": r.immutable,
            "is_executive": r.is_executive,
            "content_hash": r.content_hash,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# --- Pre-Phase 7: KPI alerts ---


@router.get("/alerts")
def list_kpi_alerts(
    status: str = Query("open"),
    priority: Optional[str] = Query(
        None, description="critical | high | medium | low"
    ),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    rows = KPIAlertService(db).list_alerts(
        tenant_id, status=status, priority=priority, limit=limit
    )
    return [
        {
            "id": r.id,
            "alert_type": r.alert_type,
            "severity": r.severity,
            "priority": r.priority,
            "correlation_id": r.correlation_id,
            "title": r.title,
            "message": r.message,
            "details": r.details,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/alerts/evaluate")
def evaluate_kpi_alerts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    result = KPIAlertService(db).evaluate_and_persist(user)
    created = result["created"]
    return {
        "created_count": len(created),
        "correlation_id": result.get("correlation_id"),
        "incidents": result.get("incidents", []),
        "alerts": [
            {
                "id": r.id,
                "alert_type": r.alert_type,
                "priority": r.priority,
                "title": r.title,
            }
            for r in created
        ],
    }


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_finance(user)
    row = KPIAlertService(db).acknowledge(alert_id, user)
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"id": row.id, "status": row.status, "acknowledged_at": row.acknowledged_at}


# --- Pre-Phase 7: async reports ---


@router.get("/reports/versions")
def get_report_versions(user: User = Depends(get_current_user)):
    _require_finance(user)
    return list_report_versions()


@router.post("/reports/async", response_model=ProcessingJobOut)
def enqueue_finance_report(
    body: AsyncReportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Queue a large finance export. Poll GET /intelligence/jobs/{id}, then download.
    """
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    version = body.report_version or settings.finance_report_version_default
    try:
        spec = resolve_report_spec(report_type=body.report_type, report_version=version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    jobs = JobService(db)
    row = jobs.create(
        user_id=user.id,
        tenant_id=tenant_id,
        job_type=JobType.FINANCE_REPORT.value,
        payload={
            "report_type": spec["report_type"],
            "report_version": spec["report_version"],
            "format": body.format,
            "months": body.months,
            "quarters": body.quarters,
            "department": body.department,
            "limit": body.limit,
        },
    )
    jobs.dispatch_finance_report(row.id, user.id)
    return jobs.to_out(row)


@router.get("/reports/{job_id}/download")
def download_finance_report(
    job_id: int,
    request: Request,
    format: str = Query("csv", pattern="^(csv|json)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download completed report; access is audited."""
    _require_finance(user)
    tenant_id = resolve_tenant_id(user)
    jobs = JobService(db)
    row = jobs.get(job_id, user_id=user.id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row.status != JobStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail=f"Job status is {row.status}")

    manifest = row.result or {}
    files = manifest.get("files") or {}
    file_path = files.get(format)
    if not file_path or not Path(file_path).is_file():
        raise HTTPException(status_code=404, detail=f"Report file ({format}) not found")

    audit = ReportAccessAuditService(db)
    audit.log_download(
        tenant_id=tenant_id,
        user=user,
        job_id=job_id,
        report_type=manifest.get("report_type", "unknown"),
        file_format=format,
        file_path=file_path,
        report_version=manifest.get("report_version"),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    media = "text/csv" if format == "csv" else "application/json"
    return FileResponse(
        path=file_path,
        media_type=media,
        filename=Path(file_path).name,
    )


@router.get("/reports/access-audit")
def list_report_access_audit(
    job_id: Optional[int] = None,
    user_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Finance admin: who downloaded executive reports."""
    if user.role not in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Finance admin required")
    tenant_id = resolve_tenant_id(user)
    svc = ReportAccessAuditService(db)
    rows = svc.list_access(tenant_id, job_id=job_id, user_id=user_id, limit=limit)
    return [svc.to_dict(r) for r in rows]


@router.post("/cache/invalidate")
def invalidate_analytics_cache(
    report: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Finance admin: bust cached analytics for tenant."""
    if user.role not in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Finance admin required")
    from app.finance.cache import AnalyticsCache

    tenant_id = resolve_tenant_id(user)
    deleted = AnalyticsCache().invalidate_prefix(tenant_id, report)
    return {"invalidated_keys": deleted, "report": report}
