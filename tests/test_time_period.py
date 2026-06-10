"""Time period preset resolution."""
from datetime import datetime

import pytest

from datetime import timedelta

from app.utils.time_period import (
    CUSTOM,
    DATE,
    LAST_MONTH,
    LAST_YEAR,
    THIS_MONTH,
    THIS_YEAR,
    assert_date_not_future,
    resolve_date_filter,
    resolve_time_period,
    today_end,
    utc_now,
)


def test_this_month_starts_on_first():
    r = resolve_time_period("this_month")
    now = datetime.utcnow()
    assert r.start_date is not None
    assert r.start_date.day == 1
    assert r.start_date.month == now.month
    assert r.end_date.date() == now.date()


def test_last_month_full_calendar_month():
    r = resolve_time_period("last_month")
    now = datetime.utcnow()
    if now.month == 1:
        assert r.start_date.month == 12
        assert r.start_date.year == now.year - 1
    else:
        assert r.start_date.month == now.month - 1
        assert r.start_date.year == now.year
    assert r.end_date.day >= 28


def test_this_year():
    r = resolve_time_period("this_year")
    now = datetime.utcnow()
    assert r.start_date.month == 1
    assert r.start_date.day == 1
    assert r.start_date.year == now.year


def test_last_year():
    r = resolve_time_period("last_year")
    now = datetime.utcnow()
    assert r.start_date.year == now.year - 1
    assert r.end_date.month == 12


def test_all_time_no_start():
    r = resolve_time_period("all_time")
    assert r.is_all_time
    assert r.start_date is None


def test_custom_requires_dates():
    with pytest.raises(ValueError, match="start_date"):
        resolve_date_filter(period="custom")


def test_custom_range():
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 31)
    r = resolve_time_period("custom", start, end)
    assert r.period == "custom"
    assert r.start_date.day == 1
    assert r.end_date.day == 31


def test_aliases():
    assert resolve_time_period("previous_month").period == LAST_MONTH
    assert resolve_time_period("previous_year").period == LAST_YEAR
    with pytest.raises(ValueError):
        resolve_time_period("not_a_period")


def test_single_date_param():
    r = resolve_date_filter(date=datetime(2026, 5, 15, 14, 30))
    assert r is not None
    assert r.period == DATE
    assert r.filter_type == "single_date"
    assert r.start_date.day == 15
    assert r.end_date.day == 15
    assert r.start_date.hour == 0
    assert r.end_date.hour == 23


def test_date_range_without_custom_period():
    r = resolve_date_filter(
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 31),
    )
    assert r is not None
    assert r.period == CUSTOM
    assert r.filter_type == "date_range"


def test_date_range_start_only_defaults_end_today():
    r = resolve_date_filter(start_date=datetime(2026, 1, 1))
    assert r is not None
    assert r.end_date.date() == datetime.utcnow().date()


def test_period_date_requires_date_param():
    with pytest.raises(ValueError, match="date"):
        resolve_date_filter(period="date")


def test_reject_future_single_date():
    tomorrow = utc_now() + timedelta(days=1)
    with pytest.raises(ValueError, match="cannot be in the future"):
        resolve_date_filter(date=tomorrow)


def test_reject_future_range_end():
    tomorrow = utc_now() + timedelta(days=1)
    with pytest.raises(ValueError, match="end_date"):
        resolve_date_filter(
            start_date=datetime(2026, 1, 1),
            end_date=tomorrow,
        )


def test_reject_future_range_start():
    tomorrow = utc_now() + timedelta(days=1)
    with pytest.raises(ValueError, match="start_date"):
        resolve_date_filter(start_date=tomorrow, end_date=tomorrow)


def test_this_month_end_is_today():
    r = resolve_time_period("this_month")
    assert r.end_date.date() == today_end().date()


def test_custom_range_end_defaults_to_today_not_future():
    r = resolve_date_filter(start_date=datetime(2026, 1, 1))
    assert r.end_date.date() == utc_now().date()
