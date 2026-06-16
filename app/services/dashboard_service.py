"""Dashboard analytics — business logic extracted from HTTP routers."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseStatus, OCRBill, TransactionType, User, Wallet
from app.schemas import (
    CategoryWiseExpense,
    DashboardOverviewResponse,
    DashboardStatsResponse,
    DateRangeInfo,
    MonthlySummary,
)
from app.utils.dashboard_queries import (
    compute_category_breakdown,
    compute_dashboard_stats,
    recent_transactions_list,
)
from app.utils.time_period import ResolvedTimePeriod, apply_bill_date_filter


class DashboardService:
    def __init__(self, db: Session):
        self.db = db

    def wallet_balance(self, user_id: int, company_id: int = 1) -> float:
        wallet = (
            self.db.query(Wallet)
            .filter(Wallet.user_id == user_id, Wallet.company_id == company_id)
            .first()
        )
        return wallet.balance if wallet else 0.0

    def _company_id(self, user: User) -> int:
        return int(getattr(user, "company_id", 1) or 1)

    def get_stats(
        self, user: User, resolved: ResolvedTimePeriod, date_range: DateRangeInfo
    ) -> DashboardStatsResponse:
        company_id = self._company_id(user)
        stats = compute_dashboard_stats(
            self.db,
            user,
            resolved,
            wallet_balance=self.wallet_balance(user.id, company_id),
            company_id=company_id,
        )
        return DashboardStatsResponse(date_range=date_range, stats=stats)

    def get_overview(
        self,
        user: User,
        resolved: ResolvedTimePeriod,
        date_range: DateRangeInfo,
        *,
        txn_type: TransactionType,
        recent_limit: int,
        top_limit: int,
    ) -> DashboardOverviewResponse:
        company_id = self._company_id(user)
        balance = self.wallet_balance(user.id, company_id)
        stats = compute_dashboard_stats(
            self.db, user, resolved, wallet_balance=balance, company_id=company_id
        )
        breakdown = compute_category_breakdown(
            self.db, user.id, resolved, txn_type, company_id=company_id
        )
        recent = recent_transactions_list(
            self.db, user.id, resolved, limit=recent_limit, company_id=company_id
        )
        top = self.top_categories(
            user_id=user.id,
            resolved=resolved,
            txn_type=txn_type,
            limit=top_limit,
            company_id=company_id,
        )
        return DashboardOverviewResponse(
            date_range=date_range,
            stats=stats,
            category_breakdown=breakdown,
            recent_transactions=recent,
            top_categories=top,
        )

    def category_breakdown(
        self,
        user_id: int,
        resolved: ResolvedTimePeriod,
        txn_type: TransactionType,
        company_id: int = 1,
    ) -> List[CategoryWiseExpense]:
        return compute_category_breakdown(
            self.db, user_id, resolved, txn_type, company_id=company_id
        )

    def monthly_trend(
        self,
        user_id: int,
        resolved: ResolvedTimePeriod,
        months: Optional[int],
        company_id: int = 1,
    ) -> List[MonthlySummary]:
        if resolved.is_all_time and months:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=30 * months)
        elif resolved.is_all_time:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=30 * 6)
        else:
            start_date = resolved.start_date
            end_date = resolved.end_date

        results = (
            self.db.query(
                extract("year", Expense.bill_date).label("year"),
                extract("month", Expense.bill_date).label("month"),
                Expense.transaction_type,
                func.sum(Expense.bill_amount).label("total"),
            )
            .filter(
                Expense.user_id == user_id,
                Expense.company_id == company_id,
                Expense.status == ExpenseStatus.APPROVED,
            )
        )
        if start_date is not None:
            results = results.filter(Expense.bill_date >= start_date)
        results = (
            results.filter(Expense.bill_date <= end_date)
            .group_by("year", "month", Expense.transaction_type)
            .order_by("year", "month")
            .all()
        )

        monthly_data = defaultdict(lambda: {"income": 0, "expense": 0})
        for result in results:
            month_key = f"{int(result.year)}-{int(result.month):02d}"
            if result.transaction_type == TransactionType.INCOME:
                monthly_data[month_key]["income"] = float(result.total)
            else:
                monthly_data[month_key]["expense"] = float(result.total)

        return [
            MonthlySummary(
                month=month_key,
                income=data["income"],
                expense=data["expense"],
                net=data["income"] - data["expense"],
            )
            for month_key, data in sorted(monthly_data.items())
        ]

    def top_categories(
        self,
        *,
        user_id: int,
        resolved: ResolvedTimePeriod,
        txn_type: TransactionType,
        limit: int,
        company_id: int = 1,
    ) -> List[Dict[str, Any]]:
        q = (
            self.db.query(
                Expense.main_category,
                func.sum(Expense.bill_amount).label("total"),
                func.count(Expense.id).label("count"),
            )
            .filter(
                Expense.user_id == user_id,
                Expense.company_id == company_id,
                Expense.status == ExpenseStatus.APPROVED,
                Expense.transaction_type == txn_type,
            )
        )
        q = apply_bill_date_filter(q, Expense, resolved)
        top_categories = (
            q.group_by(Expense.main_category)
            .order_by(func.sum(Expense.bill_amount).desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "category": cat.main_category.value,
                "total_amount": float(cat.total),
                "transaction_count": cat.count,
                "average_amount": float(cat.total) / cat.count if cat.count > 0 else 0,
            }
            for cat in top_categories
        ]

    def daily_spending(
        self, user_id: int, resolved: ResolvedTimePeriod, company_id: int = 1
    ) -> List[Dict[str, Any]]:
        q = (
            self.db.query(
                func.date(Expense.bill_date).label("date"),
                func.sum(Expense.bill_amount).label("total"),
            )
            .filter(
                Expense.user_id == user_id,
                Expense.company_id == company_id,
                Expense.status == ExpenseStatus.APPROVED,
                Expense.transaction_type == TransactionType.EXPENSE,
            )
        )
        q = apply_bill_date_filter(q, Expense, resolved)
        daily_data = q.group_by(func.date(Expense.bill_date)).order_by("date").all()
        return [
            {"date": data.date, "amount": float(data.total) if data.total else 0}
            for data in daily_data
        ]

    def pending_approvals_summary(
        self, user_id: int, company_id: int = 1
    ) -> Dict[str, Any]:
        pending = (
            self.db.query(Expense)
            .filter(
                Expense.user_id == user_id,
                Expense.company_id == company_id,
                Expense.status.in_([ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING]),
            )
            .all()
        )
        total_pending_amount = sum(e.bill_amount for e in pending)
        by_category = defaultdict(lambda: {"count": 0, "total": 0})
        for expense in pending:
            by_category[expense.main_category.value]["count"] += 1
            by_category[expense.main_category.value]["total"] += expense.bill_amount
        return {
            "total_pending_count": len(pending),
            "total_pending_amount": total_pending_amount,
            "by_category": dict(by_category),
            "oldest_pending": min([e.bill_date for e in pending]) if pending else None,
            "newest_pending": max([e.bill_date for e in pending]) if pending else None,
        }

    def ocr_statistics(
        self,
        user_id: int,
        resolved: ResolvedTimePeriod,
        date_range_meta: dict,
        company_id: int = 1,
    ) -> Dict[str, Any]:
        q = self.db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.company_id == company_id,
            Expense.upload_method == "ocr",
        )
        q = apply_bill_date_filter(q, Expense, resolved)
        ocr_expenses = q.all()

        total_scanned = len(ocr_expenses)
        approved_scanned = len(
            [e for e in ocr_expenses if e.status == ExpenseStatus.APPROVED]
        )
        pending_scanned = len(
            [
                e
                for e in ocr_expenses
                if e.status in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING)
            ]
        )
        total_ocr_amount = sum(
            e.bill_amount for e in ocr_expenses if e.status == ExpenseStatus.APPROVED
        )
        avg_confidence = (
            self.db.query(func.avg(OCRBill.confidence_score))
            .filter(OCRBill.user_id == user_id, OCRBill.company_id == company_id)
            .scalar()
        )
        return {
            "date_range": date_range_meta,
            "total_ocr_scans": total_scanned,
            "approved_ocr_scans": approved_scanned,
            "pending_ocr_scans": pending_scanned,
            "total_ocr_amount": total_ocr_amount,
            "average_confidence_score": round(avg_confidence or 0, 2),
            "approval_rate": round(
                (approved_scanned / total_scanned * 100) if total_scanned > 0 else 0, 2
            ),
        }

    def budget_vs_actual(
        self,
        user_id: int,
        *,
        month: Optional[str],
        start_date: Optional[datetime],
        end_date: datetime,
        date_range_meta: dict,
        period_label: str,
        company_id: int = 1,
    ) -> Dict[str, Any]:
        if month:
            year, month_num = map(int, month.split("-"))
            start_date = datetime(year, month_num, 1)
            if month_num == 12:
                end_date = datetime(year + 1, 1, 1) - timedelta(microseconds=1)
            else:
                end_date = datetime(year, month_num + 1, 1) - timedelta(microseconds=1)

        q = (
            self.db.query(
                Expense.main_category,
                func.sum(Expense.bill_amount).label("actual"),
            )
            .filter(
                Expense.user_id == user_id,
                Expense.company_id == company_id,
                Expense.status == ExpenseStatus.APPROVED,
                Expense.transaction_type == TransactionType.EXPENSE,
            )
        )
        if start_date is not None:
            q = q.filter(Expense.bill_date >= start_date)
        q = q.filter(Expense.bill_date <= end_date)
        actual_spending = q.group_by(Expense.main_category).all()

        return {
            "date_range": date_range_meta,
            "month": month or period_label,
            "categories": [
                {
                    "category": cat.main_category.value,
                    "actual": float(cat.actual),
                    "budget": None,
                }
                for cat in actual_spending
            ],
        }

    def quick_insights(
        self,
        user_id: int,
        resolved: ResolvedTimePeriod,
        date_range_meta: dict,
        company_id: int = 1,
    ) -> Dict[str, Any]:
        expenses = apply_bill_date_filter(
            self.db.query(Expense).filter(
                Expense.user_id == user_id,
                Expense.company_id == company_id,
                Expense.status == ExpenseStatus.APPROVED,
                Expense.transaction_type == TransactionType.EXPENSE,
            ),
            Expense,
            resolved,
        ).all()

        if not expenses:
            return {
                "date_range": date_range_meta,
                "message": "No expense data available for insights",
            }

        category_totals = defaultdict(float)
        for expense in expenses:
            category_totals[expense.main_category.value] += expense.bill_amount

        top_category = max(category_totals, key=category_totals.get)
        total_spent = sum(e.bill_amount for e in expenses)
        days_span = max(
            1,
            (resolved.end_date - (resolved.start_date or resolved.end_date)).days + 1,
        )
        avg_daily = total_spent / days_span
        biggest_expense = max(expenses, key=lambda e: e.bill_amount)
        transaction_counts = defaultdict(int)
        for expense in expenses:
            transaction_counts[expense.main_category.value] += 1
        most_frequent_category = max(transaction_counts, key=transaction_counts.get)

        return {
            "date_range": date_range_meta,
            "top_spending_category": {
                "category": top_category,
                "amount": category_totals[top_category],
            },
            "average_daily_spending": round(avg_daily, 2),
            "biggest_expense": {
                "name": biggest_expense.bill_name,
                "amount": biggest_expense.bill_amount,
                "category": biggest_expense.main_category.value,
                "date": biggest_expense.bill_date,
            },
            "most_frequent_category": {
                "category": most_frequent_category,
                "count": transaction_counts[most_frequent_category],
            },
            "total_transactions": len(expenses),
            "total_spent": total_spent,
        }
