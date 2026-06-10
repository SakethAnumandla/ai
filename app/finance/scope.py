"""Finance analytics query scope — company, department, or own."""
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy.orm import Query, Session

from app.models import Department, Expense, ExpenseStatus, TransactionType, User, UserRole


def is_company_scope(user: User) -> bool:
    return user.role in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN)


def expense_base_query(
    db: Session,
    user: User,
    *,
    start: datetime,
    end: Optional[datetime] = None,
    department: Optional[str] = None,
) -> Query:
    """Approved expenses in period; finance = company-wide unless department filter."""
    q = db.query(Expense).filter(
        Expense.status == ExpenseStatus.APPROVED,
        Expense.transaction_type == TransactionType.EXPENSE,
        Expense.bill_date >= start,
    )
    if end:
        q = q.filter(Expense.bill_date <= end)

    if department:
        try:
            dept = Department(department)
            q = q.join(User, Expense.user_id == User.id).filter(User.department == dept)
        except ValueError:
            pass
    elif is_company_scope(user):
        pass
    elif user.department:
        q = q.join(User, Expense.user_id == User.id).filter(User.department == user.department)
    else:
        q = q.filter(Expense.user_id == user.id)
    return q


def period_range(*, months: int = 1, quarters: int = 0) -> Tuple[datetime, datetime]:
    end = datetime.utcnow()
    if quarters:
        days = 90 * quarters
    else:
        days = 30 * max(1, months)
    start = end - timedelta(days=days)
    return start, end


def all_active_user_ids(db: Session, user: User, department: Optional[str] = None) -> List[int]:
    q = db.query(User.id).filter(User.is_active.is_(True))
    if department:
        try:
            q = q.filter(User.department == Department(department))
        except ValueError:
            pass
    elif not is_company_scope(user) and user.department:
        q = q.filter(User.department == user.department)
    return [r[0] for r in q.all()]
