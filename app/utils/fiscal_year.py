"""Financial year helpers (April–March, EU/IN style)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from app.data.business_taxonomy import ALLOWED_FINANCIAL_YEARS


def financial_year_label(dt: date) -> str:
    """Return FY label e.g. FY2025-26 for a calendar date."""
    if dt.month >= 4:
        start_year = dt.year
    else:
        start_year = dt.year - 1
    end_short = str(start_year + 1)[-2:]
    return f"FY{start_year}-{end_short}"


def parse_financial_year(label: str) -> Tuple[date, date]:
    """FY2025-26 → (2025-04-01, 2026-03-31)."""
    raw = (label or "").strip().upper()
    if not raw.startswith("FY") or "-" not in raw:
        raise ValueError(f"Invalid financial year label: {label}")
    body = raw[2:]
    start_s, end_s = body.split("-", 1)
    start_year = int(start_s)
    end_year = int(f"{start_year // 100}{end_s}" if len(end_s) == 2 else end_s)
    if end_year < start_year:
        end_year = start_year + 1
    return date(start_year, 4, 1), date(end_year, 3, 31)


def financial_year_range(label: str) -> Tuple[datetime, datetime]:
    start, end = parse_financial_year(label)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc)
    return start_dt, end_dt


def validate_bill_date(dt: date, *, allowed: Optional[List[str]] = None) -> str:
    """
    Ensure bill_date falls in an allowed FY window.
    Returns FY label or raises ValueError.
    """
    if isinstance(dt, datetime):
        dt = dt.date()
    fy = financial_year_label(dt)
    allowed_list = list(allowed or ALLOWED_FINANCIAL_YEARS)
    if fy not in allowed_list:
        raise ValueError(
            f"Bill date must fall within {', '.join(allowed_list)}. "
            f"Date {dt.isoformat()} is in {fy}."
        )
    return fy


def month_index_fy(dt: date) -> int:
    """1=Apr … 12=Mar within financial year."""
    return dt.month - 3 if dt.month >= 4 else dt.month + 9


def list_fy_months(label: str) -> List[dict]:
    """Months Apr–Mar for a FY with calendar year/month numbers."""
    start, _ = parse_financial_year(label)
    months = []
    y, m = start.year, 4
    names = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
    for name in names:
        months.append({"label": name, "year": y, "month": m})
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months
