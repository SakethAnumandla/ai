"""Wallet read models (transactions and summaries).

`WalletService` focuses on ledger mutation (update/revert). This module contains read queries
so routers stay thin and consistent.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.dependencies import TimePeriodFilter
from app.models import Expense, TransactionType, User, WalletTransaction
from app.schemas import (
    DateRangeInfo,
    WalletPeriodSummary,
    WalletTransactionResponse,
    WalletTransactionsPage,
)
from app.services.wallet_service import WalletService
from app.utils.time_period import apply_bill_date_filter


class WalletReadService:
    def __init__(self, db: Session):
        self.db = db

    def transactions_page(
        self,
        *,
        time_period: TimePeriodFilter,
        skip: int,
        limit: int,
        current_user: User,
        date_range: DateRangeInfo,
    ) -> WalletTransactionsPage:
        wallet = WalletService(self.db).get_or_create_wallet(
            current_user.id, getattr(current_user, "company_id", 1)
        )
        base = (
            self.db.query(WalletTransaction)
            .join(Expense, Expense.id == WalletTransaction.expense_id)
            .filter(WalletTransaction.wallet_id == wallet.id)
        )
        filtered = apply_bill_date_filter(base, Expense, time_period.resolved)
        total = filtered.count()
        rows = (
            filtered.order_by(WalletTransaction.transaction_date.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return WalletTransactionsPage(
            date_range=date_range,
            transactions=[WalletTransactionResponse.model_validate(t) for t in rows],
            total=total,
            skip=skip,
            limit=limit,
        )

    def period_summary(
        self,
        *,
        time_period: TimePeriodFilter,
        current_user: User,
        date_range: DateRangeInfo,
    ) -> WalletPeriodSummary:
        wallet = WalletService(self.db).get_or_create_wallet(
            current_user.id, getattr(current_user, "company_id", 1)
        )
        q = (
            self.db.query(WalletTransaction)
            .join(Expense, Expense.id == WalletTransaction.expense_id)
            .filter(WalletTransaction.wallet_id == wallet.id)
        )
        q = apply_bill_date_filter(q, Expense, time_period.resolved)
        transactions: List[WalletTransaction] = q.all()

        period_income = sum(
            t.amount for t in transactions if t.transaction_type == TransactionType.INCOME
        )
        period_expense = sum(
            t.amount for t in transactions if t.transaction_type == TransactionType.EXPENSE
        )

        return WalletPeriodSummary(
            date_range=date_range,
            current_balance=wallet.balance,
            period_income=period_income,
            period_expense=period_expense,
            period_net=period_income - period_expense,
            transaction_count=len(transactions),
        )

