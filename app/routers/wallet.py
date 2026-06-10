"""Wallet HTTP routes — delegates reads/writes to services."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import TimePeriodFilter, get_default_user
from app.models import User
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
    current_user: User = Depends(get_default_user),
):
    """Current wallet balance (all-time ledger; not filtered by period)."""
    wallet = WalletService(db).get_or_create_wallet(current_user.id)
    return _wallet_to_response(wallet)


@router.get("/transactions")
async def get_transactions(
    time_period: TimePeriodFilter = Depends(),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Wallet transaction history within the selected time period."""
    return WalletReadService(db).transactions_page(
        time_period=time_period,
        skip=skip,
        limit=limit,
        current_user=current_user,
        date_range=date_range_info(time_period),
    )


@router.get("/summary")
async def get_wallet_summary(
    time_period: TimePeriodFilter = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """
    Wallet summary for the selected period.

    `current_balance` is the live all-time balance; income/expense/net are for the period only.
    """
    return WalletReadService(db).period_summary(
        time_period=time_period,
        current_user=current_user,
        date_range=date_range_info(time_period),
    )


@router.get("/budget-utilisation")
async def get_budget_utilisation(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Monthly approved spend vs €1M budget; prior-month compare hidden in April (FY start)."""
    return monthly_budget_utilisation(db, current_user.id)


@router.get("/summary/legacy")
async def get_wallet_summary_legacy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """All-time wallet totals (legacy shape for older clients)."""
    wallet = WalletService(db).get_or_create_wallet(current_user.id)
    return {
        "current_balance": wallet.balance,
        "total_income": wallet.total_income,
        "total_expense": wallet.total_expense,
        "net_savings": wallet.total_income - wallet.total_expense,
    }
