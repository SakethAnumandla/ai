"""Parse natural-language date ranges for expense search workflows."""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.utils.date_parser import parse_bill_date


def _day_bounds(d: datetime) -> Tuple[datetime, datetime]:
    start = d.replace(hour=0, minute=0, second=0, microsecond=0)
    end = d.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


def _month_bounds(year: int, month: int) -> Tuple[datetime, datetime]:
    last = monthrange(year, month)[1]
    start = datetime(year, month, 1)
    end = datetime(year, month, last, 23, 59, 59, 999999)
    return start, end


def parse_date_range(text: str, *, now: Optional[datetime] = None) -> Optional[Tuple[datetime, datetime]]:
    """
    Return (start_date, end_date) inclusive, or None if not parseable.
    Examples: last week, this month, October 2024, 1 May to 15 May 2024, 2024-10-01 to 2024-10-31
    """
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    lowered = raw.lower()
    today = (now or datetime.utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)

    if lowered in ("today", "now"):
        return _day_bounds(today)
    if lowered == "yesterday":
        d = today - timedelta(days=1)
        return _day_bounds(d)
    if lowered in ("this week", "current week"):
        start = today - timedelta(days=today.weekday())
        return _day_bounds(start)[0], _day_bounds(today)[1]
    if lowered in ("last week", "previous week"):
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
        return _day_bounds(start)[0], _day_bounds(end)[1]
    if lowered in ("this month", "current month"):
        return _month_bounds(today.year, today.month)
    if lowered in ("last month", "previous month"):
        m = today.month - 1
        y = today.year
        if m < 1:
            m = 12
            y -= 1
        return _month_bounds(y, m)

    between = re.search(
        r"(?:from\s+)?(.+?)\s+(?:to|until|through|-)\s+(.+)",
        lowered,
        re.IGNORECASE,
    )
    if between:
        try:
            start = parse_bill_date(between.group(1).strip())
            end = parse_bill_date(between.group(2).strip())
            return _day_bounds(start)[0], _day_bounds(end)[1]
        except Exception:
            pass

    month_year = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"\s+(\d{4})\b",
        lowered,
    )
    if month_year:
        months = {
            "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
            "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
            "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
            "nov": 11, "november": 11, "dec": 12, "december": 12,
        }
        key = month_year.group(1).lower()
        month = months.get(key) or months.get(key[:3])
        if month:
            return _month_bounds(int(month_year.group(2)), month)

    iso_range = re.search(
        r"(\d{4}-\d{2}-\d{2})\s*(?:to|-|through)\s*(\d{4}-\d{2}-\d{2})",
        raw,
    )
    if iso_range:
        try:
            start = parse_bill_date(iso_range.group(1))
            end = parse_bill_date(iso_range.group(2))
            return _day_bounds(start)[0], _day_bounds(end)[1]
        except Exception:
            pass

    try:
        single = parse_bill_date(raw)
        return _day_bounds(single)
    except Exception:
        pass

    return None
