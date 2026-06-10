"""Seed June 2026 dashboard test data: draft, pending, approve-today, May approved."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.dependencies import DEV_USER_USERNAME
from app.models import (
    ApprovalStatus,
    Expense,
    ExpenseStatus,
    MainCategory,
    TransactionType,
    UploadMethod,
    User,
)
from app.services.expense_approval_service import (
    create_expense_approval_workflow,
    process_expense_approval,
)
from app.utils.fiscal_year import financial_year_label


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)


def _add_expense(
    db,
    user: User,
    *,
    name: str,
    amount: float,
    bill_date: datetime,
    status: ExpenseStatus,
    description: str,
) -> Expense:
    fy = financial_year_label(bill_date.date())
    exp = Expense(
        user_id=user.id,
        bill_name=name,
        bill_amount=amount,
        bill_date=bill_date,
        transaction_type=TransactionType.EXPENSE,
        main_category=MainCategory.TRAVEL,
        sub_category="local_transport",
        description=description,
        vendor_name=name,
        upload_method=UploadMethod.MANUAL,
        status=status,
        financial_year=fy,
        currency_code="EUR",
    )
    db.add(exp)
    db.flush()
    if status in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
        create_expense_approval_workflow(db, exp)
    return exp


def _approve_all_steps(db, expense: Expense, user: User, comment: str) -> None:
    db.refresh(expense)
    while True:
        pending = next(
            (
                s
                for s in sorted(expense.approval_steps, key=lambda x: x.sequence_order)
                if s.status == ApprovalStatus.PENDING
            ),
            None,
        )
        if not pending:
            break
        process_expense_approval(
            db,
            approval_id=pending.id,
            user=user,
            action="approve",
            comments=comment,
        )
        db.flush()
        db.refresh(expense)


def main() -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == DEV_USER_USERNAME).first()
        if not user:
            print("No dev user — run app once to bootstrap user.")
            sys.exit(1)

        today = datetime.now(timezone.utc).date()
        y, m, d = today.year, today.month, today.day
        two_days_ago = _dt(y, m, max(1, d - 2))
        yesterday = _dt(y, m, max(1, d - 1))
        today_dt = _dt(y, m, d)
        may_mid = _dt(y, 5, 15)

        # Remove prior seed rows (idempotent re-run).
        for name in (
            "June Draft Bill",
            "June Pending Bill",
            "June Approve Today",
            "May Approved Travel",
        ):
            old = (
                db.query(Expense)
                .filter(Expense.user_id == user.id, Expense.bill_name == name)
                .all()
            )
            for row in old:
                db.delete(row)
        db.flush()

        draft = _add_expense(
            db,
            user,
            name="June Draft Bill",
            amount=450.0,
            bill_date=yesterday,
            status=ExpenseStatus.DRAFT,
            description="Draft saved yesterday",
        )
        pending = _add_expense(
            db,
            user,
            name="June Pending Bill",
            amount=1200.0,
            bill_date=two_days_ago,
            status=ExpenseStatus.SUBMITTED,
            description="Submitted 2 days ago — awaiting approval",
        )
        approve_today = _add_expense(
            db,
            user,
            name="June Approve Today",
            amount=900.0,
            bill_date=today_dt,
            status=ExpenseStatus.SUBMITTED,
            description="Submitted today — approve with remarks",
        )
        may_approved = _add_expense(
            db,
            user,
            name="May Approved Travel",
            amount=2000.0,
            bill_date=may_mid,
            status=ExpenseStatus.SUBMITTED,
            description="May travel — auto-approve for last-month stats",
        )
        _approve_all_steps(
            db,
            may_approved,
            user,
            "Approved for May business travel — seed data.",
        )

        db.commit()

        print("Seeded expenses:")
        for e in (draft, pending, approve_today, may_approved):
            print(
                f"  id={e.id} {e.bill_name!r} "
                f"status={e.status.value} amount={e.bill_amount} "
                f"date={e.bill_date.date()}"
            )

        db.commit()
        print(
            f"\nPending approval queue should include "
            f"ids {pending.id} and {approve_today.id}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
