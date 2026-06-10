from typing import Optional, Union

from fastapi import HTTPException

from app.models import TransactionType

# Aliases for mobile / casual input
EXPENSE_ALIASES = {"expense", "out", "debit", "spend", "spent", "payment", "paid"}
INCOME_ALIASES = {"income", "in", "credit", "received", "earn", "earning"}


def _blank(value: Optional[Union[str, TransactionType]]) -> bool:
    if value is None:
        return True
    if isinstance(value, TransactionType):
        return False
    return not str(value).strip()


def coerce_transaction_type(
    value: Optional[Union[str, TransactionType]],
) -> Optional[TransactionType]:
    """Parse transaction type from query/JSON; None or blank → None."""
    if isinstance(value, TransactionType):
        return value
    if _blank(value):
        return None

    key = str(value).strip().lower()
    if key in EXPENSE_ALIASES:
        return TransactionType.EXPENSE
    if key in INCOME_ALIASES:
        return TransactionType.INCOME
    try:
        return TransactionType(key)
    except ValueError as exc:
        raise ValueError(
            f"Invalid transaction_type '{value}'. Use: expense, out, income, in"
        ) from exc


def parse_transaction_type(value: str) -> TransactionType:
    if _blank(value):
        raise HTTPException(status_code=400, detail="transaction_type is required")

    try:
        parsed = coerce_transaction_type(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    assert parsed is not None
    return parsed
