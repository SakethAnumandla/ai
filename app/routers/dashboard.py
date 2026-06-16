# routers/dashboard.py — HTTP layer only; analytics in DashboardService / ExportService.
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import TimePeriodFilter
from app.deps.scope import ExpenseScope, ScopedActor, get_expense_scope
from app.models import TransactionType
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


def _actor(scope: ExpenseScope) -> ScopedActor:
    return ScopedActor.from_scope(scope)


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    time_period: TimePeriodFilter = Depends(),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Dashboard totals for the selected time period (income/expense in range)."""
    return DashboardService(db).get_stats(
        _actor(scope), time_period.resolved, date_range_info(time_period)
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
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """All main dashboard widgets in one call — same `period` filter applied everywhere."""
    return DashboardService(db).get_overview(
        _actor(scope),
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
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Expense/income breakdown by category for the selected time period."""
    actor = _actor(scope)
    return DashboardService(db).category_breakdown(
        actor.user_id, time_period.resolved, _txn_type(transaction_type), actor.company_id
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
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Monthly income/expense trend within the selected time period."""
    actor = _actor(scope)
    return DashboardService(db).monthly_trend(
        actor.user_id, time_period.resolved, months, company_id=actor.company_id
    )


@router.get("/recent-transactions")
async def get_recent_transactions(
    time_period: TimePeriodFilter = Depends(),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Recent approved transactions in the period, plus the latest upload (any date/status)."""
    actor = _actor(scope)
    return recent_transactions_list(
        db,
        actor.user_id,
        time_period.resolved,
        limit=limit,
        company_id=actor.company_id,
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
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Top categories by spend/earn in the selected time period."""
    actor = _actor(scope)
    return DashboardService(db).top_categories(
        user_id=actor.user_id,
        resolved=time_period.resolved,
        txn_type=_txn_type(transaction_type),
        limit=limit,
        company_id=actor.company_id,
    )


@router.get("/daily-spending")
async def get_daily_spending(
    time_period: TimePeriodFilter = Depends(),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Daily expense totals within the selected time period."""
    actor = _actor(scope)
    return DashboardService(db).daily_spending(
        actor.user_id, time_period.resolved, company_id=actor.company_id
    )


@router.get("/pending-approvals-summary")
async def get_pending_approvals_summary(
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Summary of pending approvals (not filtered by period — open workflow items)."""
    return DashboardService(db).pending_approvals_summary(
        _actor(scope).user_id, company_id=scope.company_id
    )


@router.get("/ocr-statistics")
async def get_ocr_statistics(
    time_period: TimePeriodFilter = Depends(),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """OCR scan statistics for the selected time period."""
    actor = _actor(scope)
    return DashboardService(db).ocr_statistics(
        actor.user_id, time_period.resolved, time_period.as_meta(), company_id=actor.company_id
    )


@router.get("/budget-vs-actual")
async def get_budget_vs_actual(
    time_period: TimePeriodFilter = Depends(),
    month: Optional[str] = None,
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Compare actual spending vs budget for the selected period or YYYY-MM month."""
    actor = _actor(scope)
    return DashboardService(db).budget_vs_actual(
        actor.user_id,
        month=month,
        start_date=time_period.start_date,
        end_date=time_period.end_date,
        date_range_meta=time_period.as_meta(),
        period_label=time_period.resolved.label,
        company_id=actor.company_id,
    )


@router.get("/export-data")
async def export_expense_data(
    time_period: TimePeriodFilter = Depends(),
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Export approved expenses in the selected time period."""
    try:
        actor = _actor(scope)
        export_service = ExportService(db)
        rows = export_service.list_approved_for_period(
            actor.user_id, time_period.resolved, company_id=actor.company_id
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
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Quick spending insights for the selected time period."""
    actor = _actor(scope)
    return DashboardService(db).quick_insights(
        actor.user_id, time_period.resolved, time_period.as_meta(), company_id=actor.company_id
    )
