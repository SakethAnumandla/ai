"""Duplicate detection by file content hash (SHA-256)."""
from typing import List, Optional

from sqlalchemy.orm import Session, joinedload

from app.models import Expense, ExpenseFile


def find_expense_by_file_hash(
    db: Session, user_id: int, file_hash: str, company_id: int = 1
) -> Optional[Expense]:
    """Return an existing expense for this user if the same file was already uploaded."""
    if not file_hash:
        return None

    via_files = (
        db.query(Expense)
        .join(ExpenseFile, ExpenseFile.expense_id == Expense.id)
        .options(joinedload(Expense.files))
        .filter(
            Expense.user_id == user_id,
            Expense.company_id == company_id,
            ExpenseFile.file_hash == file_hash,
        )
        .order_by(Expense.id.desc())
        .first()
    )
    if via_files:
        return via_files

    return (
        db.query(Expense)
        .options(joinedload(Expense.files))
        .filter(
            Expense.user_id == user_id,
            Expense.company_id == company_id,
            Expense.file_hash == file_hash,
        )
        .order_by(Expense.id.desc())
        .first()
    )


def find_duplicate_hashes(
    db: Session, user_id: int, file_hashes: List[str]
) -> dict[str, Expense]:
    """Map each hash that already exists to its expense (newest first)."""
    result: dict[str, Expense] = {}
    for h in file_hashes:
        if not h or h in result:
            continue
        expense = find_expense_by_file_hash(db, user_id, h)
        if expense:
            result[h] = expense
    return result
