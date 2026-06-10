"""Validation helpers for expense create/update/submit flows."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

from app.models import Expense, ExpenseStatus, MainCategory, TransactionType


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def validate_expense_date_not_future(bill_date: datetime) -> datetime:
    """Expense date must be today or in the past (no future dates)."""
    if bill_date.tzinfo is not None:
        check_date = bill_date.replace(tzinfo=None)
    else:
        check_date = bill_date
    today_end = utc_now_naive().replace(hour=23, minute=59, second=59, microsecond=999999)
    if check_date > today_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expense date cannot be in the future. Select today or an earlier date.",
        )
    return bill_date


def expense_is_editable(expense: Expense) -> bool:
    """Only drafts and rejected expenses can be edited."""
    return expense.status in (ExpenseStatus.DRAFT, ExpenseStatus.REJECTED)


def assert_expense_editable(expense: Expense) -> None:
    if not expense_is_editable(expense):
        if expense.status in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Submitted expenses cannot be edited. Wait for approval or rejection.",
            )
        if expense.status == ExpenseStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Approved expenses cannot be edited.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expense with status '{expense.status.value}' cannot be edited.",
        )


def validate_required_draft_fields(
    *,
    bill_name: Optional[str],
    bill_amount: Optional[float],
    main_category: Optional[MainCategory],
) -> None:
    """Minimum fields required to persist a draft."""
    missing = []
    if not bill_name or not str(bill_name).strip():
        missing.append("expense_name")
    if bill_amount is None or bill_amount <= 0:
        missing.append("amount")
    if main_category is None:
        missing.append("category")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Required fields missing to save draft: expense name, amount, and category.",
                "missing_fields": missing,
            },
        )


def draft_has_minimum_fields(expense: Expense) -> bool:
    return bool(
        expense.bill_name
        and expense.bill_name.strip()
        and expense.bill_amount
        and expense.bill_amount > 0
        and expense.main_category is not None
    )


def force_expense_transaction_type() -> TransactionType:
    """This app tracks expenses only (no income on manual entry)."""
    return TransactionType.EXPENSE


def is_awaiting_approval(status: ExpenseStatus) -> bool:
    return status in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING)


def approval_status_for(expense: Expense) -> Optional[str]:
    if expense.status in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
        return "pending"
    if expense.status == ExpenseStatus.APPROVED:
        return "approved"
    if expense.status == ExpenseStatus.REJECTED:
        return "rejected"
    return None
