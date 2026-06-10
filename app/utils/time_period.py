"""Resolve preset and custom date ranges for expenses, wallet, and dashboard."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.utils.fiscal_year import financial_year_label, parse_financial_year

# Canonical period keys (also accept snake_case aliases via normalize)
THIS_MONTH = "this_month"
LAST_MONTH = "last_month"
THIS_YEAR = "this_year"
LAST_YEAR = "last_year"
ALL_TIME = "all_time"
CUSTOM = "custom"
DATE = "date"  # single calendar day

PERIOD_ALIASES = {
    "this_month": THIS_MONTH,
    "this-month": THIS_MONTH,
    "current_month": THIS_MONTH,
    "month": THIS_MONTH,
    "last_month": LAST_MONTH,
    "last-month": LAST_MONTH,
    "previous_month": LAST_MONTH,
    "this_year": THIS_YEAR,
    "this-year": THIS_YEAR,
    "current_year": THIS_YEAR,
    "year": THIS_YEAR,
    "last_year": LAST_YEAR,
    "last-year": LAST_YEAR,
    "previous_year": LAST_YEAR,
    "all_time": ALL_TIME,
    "all-time": ALL_TIME,
    "all": ALL_TIME,
    "custom": CUSTOM,
    "custom_range": CUSTOM,
    "range": CUSTOM,
    "date_range": CUSTOM,
    "date": DATE,
    "custom_date": DATE,
    "single_date": DATE,
    "pick_date": DATE,
    "on_date": DATE,
}

TIME_PERIOD_OPTIONS: List[Dict[str, Any]] = [
    {"value": THIS_MONTH, "label": "This month", "type": "preset"},
    {"value": LAST_MONTH, "label": "Last month", "type": "preset"},
    {"value": THIS_YEAR, "label": "This financial year", "type": "preset"},
    {"value": LAST_YEAR, "label": "Previous financial year", "type": "preset"},
    {"value": ALL_TIME, "label": "All time", "type": "preset"},
    {
        "value": DATE,
        "label": "Custom date",
        "type": "single_date",
        "params": ["date"],
        "description": "One calendar day (today or earlier)",
    },
    {
        "value": CUSTOM,
        "label": "Custom range",
        "type": "date_range",
        "params": ["start_date", "end_date"],
        "description": "From–to through today only (end defaults to today)",
    },
]

DATE_FILTER_PARAMS = {
    "period": "Preset or custom: this_month, …, date, custom",
    "date": "Single day (ISO). Today or earlier only",
    "start_date": "Range start (ISO). Today or earlier only",
    "end_date": "Range end (ISO). Today or earlier; defaults to today if omitted",
    "max_date": "Latest selectable date (UTC calendar day) — same as today",
}


def utc_now() -> datetime:
    return datetime.utcnow()


def today_end() -> datetime:
    """End of current UTC calendar day — upper bound for all filters."""
    return end_of_day(utc_now())


def end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _naive_utc(dt: datetime) -> datetime:
    """Strip timezone for comparisons and DB filters (query params often include Z)."""
    if dt.tzinfo is not None:
        from datetime import timezone

        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _calendar_date(dt: datetime) -> datetime:
    """Normalize to date for comparison (strip tz if present)."""
    return start_of_day(_naive_utc(dt))


def assert_date_not_future(dt: datetime, field_name: str) -> None:
    """Reject filter dates after today (UTC)."""
    if _calendar_date(dt).date() > utc_now().date():
        raise ValueError(
            f"{field_name} cannot be in the future. "
            f"Use today ({utc_now().date().isoformat()}) or an earlier date."
        )


def max_selectable_date_iso() -> str:
    return utc_now().date().isoformat()


def _finalize_period(resolved: ResolvedTimePeriod) -> ResolvedTimePeriod:
    """Ensure resolved range never extends beyond end of today."""
    cap = today_end()
    if resolved.end_date > cap:
        end = cap
        start = resolved.start_date
        if start is not None and start > end:
            start = end
        return ResolvedTimePeriod(
            period=resolved.period,
            start_date=start,
            end_date=end,
            label=_format_label(start, end, resolved.period),
            is_all_time=resolved.is_all_time,
            filter_type=resolved.filter_type,
        )
    return resolved


def normalize_period_key(period: Optional[str], *, default: str = THIS_MONTH) -> str:
    if not period or not str(period).strip():
        return default
    key = str(period).strip().lower()
    if key not in PERIOD_ALIASES:
        valid = ", ".join(
            sorted({THIS_MONTH, LAST_MONTH, THIS_YEAR, LAST_YEAR, ALL_TIME, CUSTOM, DATE})
        )
        raise ValueError(f"Invalid period '{period}'. Use one of: {valid}")
    return PERIOD_ALIASES[key]


@dataclass(frozen=True)
class ResolvedTimePeriod:
    period: str
    start_date: Optional[datetime]
    end_date: datetime
    label: str
    is_all_time: bool
    filter_type: str = "preset"  # preset | single_date | date_range

    def as_dict(self) -> dict:
        return {
            "period": self.period,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat(),
            "label": self.label,
            "is_all_time": self.is_all_time,
            "filter_type": self.filter_type,
        }


def _month_bounds(year: int, month: int) -> Tuple[datetime, datetime]:
    last_day = monthrange(year, month)[1]
    start = datetime(year, month, 1, 0, 0, 0)
    end = datetime(year, month, last_day, 23, 59, 59, 999999)
    return start, end


def _format_label(start: Optional[datetime], end: datetime, period: str) -> str:
    if period == ALL_TIME:
        return "All time"
    if not start:
        return end.strftime("%b %d, %Y")
    if start.date() == end.date():
        return start.strftime("%b %d, %Y")
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
    if start.year == end.year:
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
    return f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"


def _resolve_single_date(day: datetime) -> ResolvedTimePeriod:
    day = _naive_utc(day)
    assert_date_not_future(day, "date")
    start = start_of_day(day)
    end = end_of_day(day)
    return _finalize_period(
        ResolvedTimePeriod(
            period=DATE,
            start_date=start,
            end_date=end,
            label=_format_label(start, end, DATE),
            is_all_time=False,
            filter_type="single_date",
        )
    )


def _resolve_date_range(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> ResolvedTimePeriod:
    if start_date is None and end_date is None:
        raise ValueError("Provide start_date and/or end_date for a custom range.")

    if start_date is not None:
        assert_date_not_future(start_date, "start_date")
    if end_date is not None:
        assert_date_not_future(end_date, "end_date")

    start = (
        start_of_day(_naive_utc(start_date))
        if start_date
        else datetime(2000, 1, 1, 0, 0, 0)
    )
    end = end_of_day(_naive_utc(end_date)) if end_date else today_end()

    if start > end:
        raise ValueError("start_date must be on or before end_date.")

    return _finalize_period(
        ResolvedTimePeriod(
            period=CUSTOM,
            start_date=start,
            end_date=end,
            label=_format_label(start, end, CUSTOM),
            is_all_time=False,
            filter_type="date_range",
        )
    )


def _resolve_preset(period: Optional[str], *, default_period: str = THIS_MONTH) -> ResolvedTimePeriod:
    """Calendar presets only (no date / start_date / end_date params)."""
    key = normalize_period_key(period, default=default_period)
    today_end_val = today_end()

    if key in (DATE, CUSTOM):
        raise ValueError(
            f"period={key} requires date or start_date/end_date query params."
        )

    now = utc_now()

    if key == ALL_TIME:
        return _finalize_period(
            ResolvedTimePeriod(
                period=key,
                start_date=None,
                end_date=today_end_val,
                label="All time",
                is_all_time=True,
                filter_type="preset",
            )
        )

    if key == THIS_MONTH:
        start, _ = _month_bounds(now.year, now.month)
        end = today_end_val
    elif key == LAST_MONTH:
        if now.month == 1:
            y, m = now.year - 1, 12
        else:
            y, m = now.year, now.month - 1
        start, end = _month_bounds(y, m)
    elif key == THIS_YEAR:
        fy_label = financial_year_label(now.date())
        fy_start, _fy_end = parse_financial_year(fy_label)
        start = datetime(fy_start.year, fy_start.month, fy_start.day, 0, 0, 0)
        end = today_end_val
    elif key == LAST_YEAR:
        curr_fy = financial_year_label(now.date())
        curr_start, _ = parse_financial_year(curr_fy)
        prev_end = curr_start - timedelta(days=1)
        prev_fy = financial_year_label(prev_end)
        prev_start, prev_end_date = parse_financial_year(prev_fy)
        start = datetime(prev_start.year, prev_start.month, prev_start.day, 0, 0, 0)
        end = datetime(
            prev_end_date.year,
            prev_end_date.month,
            prev_end_date.day,
            23,
            59,
            59,
            999999,
        )
    else:
        raise ValueError(f"Unhandled period: {key}")

    return _finalize_period(
        ResolvedTimePeriod(
            period=key,
            start_date=start,
            end_date=end,
            label=_format_label(start, end, key),
            is_all_time=False,
            filter_type="preset",
        )
    )


def resolve_date_filter(
    period: Optional[str] = None,
    date: Optional[datetime] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    default_period: Optional[str] = THIS_MONTH,
) -> Optional[ResolvedTimePeriod]:
    """
    Resolve time filter from presets, a single date, or a date range.

    Priority:
    1. `date` query param → single calendar day
    2. `start_date` / `end_date` → custom range (period=custom not required)
    3. `period` preset (this_month, last_month, …)
    """
    has_period = period is not None and str(period).strip()
    has_range = start_date is not None or end_date is not None

    if date is not None:
        return _resolve_single_date(date)

    if has_range:
        return _resolve_date_range(start_date, end_date)

    if not has_period:
        return None

    key = normalize_period_key(period, default=default_period or THIS_MONTH)

    if key == DATE:
        raise ValueError(
            "For period=date (custom date), pass the `date` query param "
            "(e.g. date=2026-05-15 or date=2026-05-15T00:00:00)."
        )

    if key == CUSTOM:
        raise ValueError(
            "For period=custom, pass start_date and/or end_date query params."
        )

    return _resolve_preset(period, default_period=default_period or THIS_MONTH)


def resolve_time_period(
    period: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    *,
    default_period: str = THIS_MONTH,
) -> ResolvedTimePeriod:
    """
    Resolve a preset time filter to [start_date, end_date] (inclusive, UTC naive).

    For single date or arbitrary ranges, use resolve_date_filter().
    """
    result = resolve_date_filter(
        period=period,
        date=None,
        start_date=start_date,
        end_date=end_date,
        default_period=default_period,
    )
    if result is not None:
        return result
    return _resolve_preset(period, default_period=default_period)


def apply_bill_date_filter(query, model, resolved: ResolvedTimePeriod):
    """Filter SQLAlchemy query on expense bill_date (or any datetime column)."""
    if resolved.is_all_time:
        return query
    col = model.bill_date
    if resolved.start_date is not None:
        query = query.filter(col >= resolved.start_date)
    return query.filter(col <= resolved.end_date)
