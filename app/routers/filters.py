"""Filter metadata for mobile/web clients."""
from fastapi import APIRouter

from app.utils.time_period import (
    DATE_FILTER_PARAMS,
    TIME_PERIOD_OPTIONS,
    max_selectable_date_iso,
    today_end,
)

router = APIRouter(prefix="/filters", tags=["filters"])


@router.get("/time-periods")
async def list_time_periods():
    """
    Time filters for dashboard, wallet, and expenses.

    **Presets** — pass `period` only:
    - this_month, last_month, this_year, last_year, all_time

    **Custom date (single day)** — pass `date`:
    - `?date=2026-05-15` or `?period=date&date=2026-05-15T00:00:00`

    **Custom range** — pass `start_date` and `end_date` (period=custom optional):
    - `?start_date=2026-01-01T00:00:00&end_date=2026-05-20T23:59:59`
  - `?start_date=2026-01-01T00:00:00` (end defaults to today)
    """
    max_day = max_selectable_date_iso()
    return {
        "periods": TIME_PERIOD_OPTIONS,
        "date_params": DATE_FILTER_PARAMS,
        "max_date": max_day,
        "max_datetime": today_end().isoformat(),
        "rules": [
            "All filters end at today (UTC); future dates are rejected with HTTP 400.",
            "Custom range: start_date and end_date must be today or earlier.",
            "Single-day filter: date must be today or earlier.",
        ],
        "usage": {
            "preset_example": "/dashboard/overview?period=this_month",
            "single_date_example": "/expenses?date=2026-05-15",
            "single_date_with_period": "/dashboard/stats?period=date&date=2026-05-15",
            "date_range_example": (
                "/wallet/transactions"
                "?start_date=2026-01-01T00:00:00&end_date=2026-05-31T23:59:59"
            ),
            "date_range_custom_period": (
                "/expenses?period=custom"
                "&start_date=2026-01-01T00:00:00&end_date=2026-05-31T23:59:59"
            ),
        },
    }
