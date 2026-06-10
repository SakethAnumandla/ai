from datetime import datetime
from typing import Optional

from fastapi import HTTPException

DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
)


def parse_bill_date(value: str) -> datetime:
    """Parse common date strings and ensure date is not in the future."""
    if not value or not str(value).strip():
        raise HTTPException(status_code=400, detail="expense_date is required")

    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    parsed: Optional[datetime] = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass

    if parsed is None:
        for fmt in DATE_FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid expense_date. Use formats like 15/05/2026, 15-05-2026, "
                "2026-05-15, or ISO datetime."
            ),
        )

    from app.utils.expense_validation import validate_expense_date_not_future

    return validate_expense_date_not_future(parsed)
