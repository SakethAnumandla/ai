"""Shared HTTP-layer helpers (date range metadata for responses)."""
from app.dependencies import TimePeriodFilter
from app.schemas import DateRangeInfo


def date_range_info(time_period: TimePeriodFilter) -> DateRangeInfo:
    r = time_period.resolved
    return DateRangeInfo(
        period=r.period,
        start_date=r.start_date,
        end_date=r.end_date,
        label=r.label,
        is_all_time=r.is_all_time,
        filter_type=r.filter_type,
    )
