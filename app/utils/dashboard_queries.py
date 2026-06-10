"""Shared dashboard query helpers with time-period filtering."""
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseStatus, TransactionType, User
from app.schemas import CategoryWiseExpense, DashboardStats
from app.utils.time_period import ResolvedTimePeriod, apply_bill_date_filter


def expense_status_display(status: ExpenseStatus) -> str:
    """API-facing status; legacy pending is shown as submitted."""
    if status == ExpenseStatus.PENDING:
        return ExpenseStatus.SUBMITTED.value
    return status.value


def serialize_recent_transaction(
    expense: Expense,
    *,
    is_latest_upload: bool = False,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": expense.id,
        "bill_name": expense.bill_name,
        "bill_amount": expense.bill_amount,
        "bill_date": expense.bill_date,
        "transaction_type": expense.transaction_type.value,
        "category": expense.main_category.value,
        "sub_category": expense.sub_category,
        "vendor_name": expense.vendor_name,
        "status": expense_status_display(expense.status),
        "upload_method": expense.upload_method.value,
        "created_at": expense.created_at,
        "updated_at": expense.updated_at,
    }
    if is_latest_upload:
        row["is_latest_upload"] = True
    return row


def merge_latest_upload(
    rows: List[Dict[str, Any]],
    latest: Optional[Expense],
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    """Ensure the most recently created expense appears even outside the period filter."""
    if not latest:
        return rows[:limit]

    seen = {r["id"] for r in rows}
    if latest.id in seen:
        return rows[:limit]

    merged = [serialize_recent_transaction(latest, is_latest_upload=True), *rows]
    return merged[:limit]


def approved_expenses_query(
    db: Session,
    user_id: int,
    time_period: ResolvedTimePeriod,
):
    q = db.query(Expense).filter(
        Expense.user_id == user_id,
        Expense.status == ExpenseStatus.APPROVED,
    )
    return apply_bill_date_filter(q, Expense, time_period)


def compute_dashboard_stats(
    db: Session,
    user: User,
    time_period: ResolvedTimePeriod,
    *,
    wallet_balance: float,
) -> DashboardStats:
    approved = approved_expenses_query(db, user.id, time_period).all()
    total_income = sum(
        e.bill_amount for e in approved if e.transaction_type == TransactionType.INCOME
    )
    total_expense = sum(
        e.bill_amount for e in approved if e.transaction_type == TransactionType.EXPENSE
    )

    pending_q = db.query(Expense).filter(
        Expense.user_id == user.id,
        Expense.status.in_([ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING]),
    )
    draft_q = db.query(Expense).filter(
        Expense.user_id == user.id,
        Expense.status == ExpenseStatus.DRAFT,
    )
    if not time_period.is_all_time:
        pending_q = apply_bill_date_filter(pending_q, Expense, time_period)
        draft_q = apply_bill_date_filter(draft_q, Expense, time_period)

    pending_approvals = pending_q.count()
    draft_expenses = draft_q.count()

    return DashboardStats(
        total_balance=wallet_balance,
        total_income=total_income,
        total_expense=total_expense,
        pending_approvals=pending_approvals,
        draft_expenses=draft_expenses,
    )


def compute_category_breakdown(
    db: Session,
    user_id: int,
    time_period: ResolvedTimePeriod,
    transaction_type: TransactionType,
) -> List[CategoryWiseExpense]:
    q = (
        db.query(
            Expense.main_category,
            func.sum(Expense.bill_amount).label("total_amount"),
            func.count(Expense.id).label("count"),
        )
        .filter(
            Expense.user_id == user_id,
            Expense.status == ExpenseStatus.APPROVED,
            Expense.transaction_type == transaction_type,
        )
    )
    q = apply_bill_date_filter(q, Expense, time_period)
    rows = q.group_by(Expense.main_category).all()
    total = sum(r.total_amount for r in rows)
    result = []
    for row in rows:
        pct = (row.total_amount / total * 100) if total > 0 else 0
        result.append(
            CategoryWiseExpense(
                category=row.main_category.value,
                total_amount=float(row.total_amount),
                percentage=round(pct, 2),
                count=row.count,
            )
        )
    result.sort(key=lambda x: x.total_amount, reverse=True)
    return result


def recent_transactions_list(
    db: Session,
    user_id: int,
    time_period: ResolvedTimePeriod,
    *,
    limit: int = 10,
) -> list:
    approved = (
        approved_expenses_query(db, user_id, time_period)
        .order_by(Expense.bill_date.desc())
        .limit(limit)
        .all()
    )
    rows = [serialize_recent_transaction(t) for t in approved]

    latest_upload = (
        db.query(Expense)
        .filter(Expense.user_id == user_id)
        .order_by(Expense.created_at.desc())
        .first()
    )
    return merge_latest_upload(rows, latest_upload, limit=limit)
