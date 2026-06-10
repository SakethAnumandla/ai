"""Analytics service for AI tools — no direct repository access from orchestrator."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseStatus, TransactionType, User, Department


class AnalyticsService:
    def __init__(self, db: Session):
        self._db = db

    def monthly_spend(
        self,
        *,
        user: User,
        months: int = 1,
        department_scope: bool = False,
    ) -> Dict[str, Any]:
        end = datetime.utcnow()
        start = end - timedelta(days=30 * max(1, months))
        q = self._db.query(Expense).filter(
            Expense.status == ExpenseStatus.APPROVED,
            Expense.transaction_type == TransactionType.EXPENSE,
            Expense.bill_date >= start,
            Expense.bill_date <= end,
        )
        if department_scope and user.department:
            q = q.join(User, Expense.user_id == User.id).filter(
                User.department == user.department
            )
        else:
            q = q.filter(Expense.user_id == user.id)

        rows = q.all()
        total = sum(e.bill_amount for e in rows)
        by_month: Dict[str, float] = {}
        for e in rows:
            key = e.bill_date.strftime("%Y-%m") if e.bill_date else "unknown"
            by_month[key] = by_month.get(key, 0) + e.bill_amount

        return {
            "total_spend": round(total, 2),
            "expense_count": len(rows),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "by_month": by_month,
        }

    def vendor_breakdown(
        self,
        *,
        user: User,
        limit: int = 10,
        department_scope: bool = False,
    ) -> Dict[str, Any]:
        end = datetime.utcnow()
        start = end - timedelta(days=30)
        q = self._db.query(
            Expense.vendor_name,
            func.sum(Expense.bill_amount).label("total"),
            func.count(Expense.id).label("count"),
        ).filter(
            Expense.status == ExpenseStatus.APPROVED,
            Expense.transaction_type == TransactionType.EXPENSE,
            Expense.bill_date >= start,
        )
        if department_scope and user.department:
            q = q.join(User, Expense.user_id == User.id).filter(
                User.department == user.department
            )
        else:
            q = q.filter(Expense.user_id == user.id)

        rows = (
            q.group_by(Expense.vendor_name)
            .order_by(func.sum(Expense.bill_amount).desc())
            .limit(limit)
            .all()
        )
        vendors = [
            {
                "vendor": r.vendor_name or "Unknown",
                "total": round(float(r.total or 0), 2),
                "count": int(r.count or 0),
            }
            for r in rows
        ]
        return {"vendors": vendors, "period_days": 30}
