"""Wallet HTTP routes — delegates reads/writes to services."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import TimePeriodFilter
from app.deps.scope import ExpenseScope, ScopedActor, get_expense_scope
from app.schemas import WalletResponse
from app.services.budget_service import monthly_budget_utilisation
from app.services.wallet_read_service import WalletReadService
from app.services.wallet_service import WalletService
from app.utils.http_helpers import date_range_info

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _wallet_to_response(wallet) -> WalletResponse:
    return WalletResponse(
        id=wallet.id,
        user_id=wallet.user_id,
        balance=wallet.balance,
        total_income=wallet.total_income or 0.0,
        total_expense=wallet.total_expense or 0.0,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at or wallet.created_at,
    )


@router.get("/balance", response_model=WalletResponse)
async def get_wallet_balance(
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Current wallet balance (all-time ledger; not filtered by period)."""
    wallet = WalletService(db).get_or_create_wallet_for_scope(scope)
    return _wallet_to_response(wallet)


@router.get("/transactions")
async def get_transactions(
    time_period: TimePeriodFilter = Depends(),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Wallet transaction history within the selected time period."""
    actor = ScopedActor.from_scope(scope)
    return WalletReadService(db).transactions_page(
        time_period=time_period,
        skip=skip,
        limit=limit,
        current_user=actor,
        date_range=date_range_info(time_period),
    )


@router.get("/summary")
async def get_wallet_summary(
    time_period: TimePeriodFilter = Depends(),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """
    Wallet summary for the selected period.

    `current_balance` is the live all-time balance; income/expense/net are for the period only.
    """
    actor = ScopedActor.from_scope(scope)
    return WalletReadService(db).period_summary(
        time_period=time_period,
        current_user=actor,
        date_range=date_range_info(time_period),
    )


@router.get("/budget-utilisation")
async def get_budget_utilisation(
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Monthly approved spend vs €1M budget; prior-month compare hidden in April (FY start)."""
    return monthly_budget_utilisation(db, scope.user_id, company_id=scope.company_id)


@router.get("/summary/legacy")
async def get_wallet_summary_legacy(
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """All-time wallet totals (legacy shape for older clients)."""
    wallet = WalletService(db).get_or_create_wallet_for_scope(scope)
    return {
        "current_balance": wallet.balance,
        "total_income": wallet.total_income,
        "total_expense": wallet.total_expense,
        "net_savings": wallet.total_income - wallet.total_expense,
    }
