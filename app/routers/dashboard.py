# routers/dashboard.py — HTTP layer only; analytics in DashboardService / ExportService.
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import TimePeriodFilter, get_default_user
from app.models import TransactionType, User
from app.schemas import CategoryWiseExpense, DashboardOverviewResponse, DashboardStatsResponse, MonthlySummary
from app.services.dashboard_service import DashboardService
from app.services.export_service import ExportService
from app.utils.dashboard_queries import recent_transactions_list
from app.utils.http_helpers import date_range_info
from app.utils.transaction_parser import coerce_transaction_type

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _txn_type(raw: Optional[str]) -> TransactionType:
    try:
        return coerce_transaction_type(raw) or TransactionType.EXPENSE
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    time_period: TimePeriodFilter = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Dashboard totals for the selected time period (income/expense in range)."""
    service = DashboardService(db)
    return service.get_stats(
        current_user, time_period.resolved, date_range_info(time_period)
    )


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    time_period: TimePeriodFilter = Depends(),
    transaction_type: Optional[str] = Query(
        None,
        description="expense, out, income, in — default expense for breakdown",
    ),
    recent_limit: int = Query(10, ge=1, le=50),
    top_limit: int = Query(5, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """All main dashboard widgets in one call — same `period` filter applied everywhere."""
    service = DashboardService(db)
    return service.get_overview(
        current_user,
        time_period.resolved,
        date_range_info(time_period),
        txn_type=_txn_type(transaction_type),
        recent_limit=recent_limit,
        top_limit=top_limit,
    )


@router.get("/category-breakdown", response_model=List[CategoryWiseExpense])
async def get_category_breakdown(
    time_period: TimePeriodFilter = Depends(),
    transaction_type: Optional[str] = Query(
        None,
        description="expense, out, income, in — default expense",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Expense/income breakdown by category for the selected time period."""
    return DashboardService(db).category_breakdown(
        current_user.id, time_period.resolved, _txn_type(transaction_type)
    )


@router.get("/monthly-trend", response_model=List[MonthlySummary])
async def get_monthly_trend(
    time_period: TimePeriodFilter = Depends(),
    months: int = Query(
        None,
        ge=1,
        le=24,
        description="Override: number of months (ignored if period is set)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Monthly income/expense trend within the selected time period."""
    return DashboardService(db).monthly_trend(
        current_user.id, time_period.resolved, months
    )


@router.get("/recent-transactions")
async def get_recent_transactions(
    time_period: TimePeriodFilter = Depends(),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Recent approved transactions in the period, plus the latest upload (any date/status)."""
    return recent_transactions_list(
        db, current_user.id, time_period.resolved, limit=limit
    )


@router.get("/top-categories")
async def get_top_categories(
    time_period: TimePeriodFilter = Depends(),
    limit: int = Query(5, ge=1, le=10),
    transaction_type: Optional[str] = Query(
        None,
        description="expense, out, income, in — default expense",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Top categories by spend/earn in the selected time period."""
    return DashboardService(db).top_categories(
        user_id=current_user.id,
        resolved=time_period.resolved,
        txn_type=_txn_type(transaction_type),
        limit=limit,
    )


@router.get("/daily-spending")
async def get_daily_spending(
    time_period: TimePeriodFilter = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Daily expense totals within the selected time period."""
    return DashboardService(db).daily_spending(
        current_user.id, time_period.resolved
    )


@router.get("/pending-approvals-summary")
async def get_pending_approvals_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Summary of pending approvals (not filtered by period — open workflow items)."""
    return DashboardService(db).pending_approvals_summary(current_user.id)


@router.get("/ocr-statistics")
async def get_ocr_statistics(
    time_period: TimePeriodFilter = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """OCR scan statistics for the selected time period."""
    return DashboardService(db).ocr_statistics(
        current_user.id, time_period.resolved, time_period.as_meta()
    )


@router.get("/budget-vs-actual")
async def get_budget_vs_actual(
    time_period: TimePeriodFilter = Depends(),
    month: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Compare actual spending vs budget for the selected period or YYYY-MM month."""
    return DashboardService(db).budget_vs_actual(
        current_user.id,
        month=month,
        start_date=time_period.start_date,
        end_date=time_period.end_date,
        date_range_meta=time_period.as_meta(),
        period_label=time_period.resolved.label,
    )


@router.get("/export-data")
async def export_expense_data(
    time_period: TimePeriodFilter = Depends(),
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Export approved expenses in the selected time period."""
    try:
        export_service = ExportService(db)
        rows = export_service.list_approved_for_period(
            current_user.id, time_period.resolved
        )
        if format == "csv":
            label = time_period.resolved.period.replace("_", "-")
            csv_body, disposition = ExportService.csv_from_rows(
                rows, f"expenses_{label}.csv"
            )
            response = StreamingResponse(iter([csv_body]), media_type="text/csv")
            response.headers["Content-Disposition"] = disposition
            return response
        return {"date_range": time_period.as_meta(), "expenses": rows}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Export failed: {exc}") from exc


@router.get("/quick-insights")
async def get_quick_insights(
    time_period: TimePeriodFilter = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Quick spending insights for the selected time period."""
    return DashboardService(db).quick_insights(
        current_user.id, time_period.resolved, time_period.as_meta()
    )
