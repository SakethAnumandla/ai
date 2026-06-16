"""Monthly budget utilisation (EUR) for wallet card and FY grid."""
from __future__ import annotations

import calendar
from calendar import monthrange
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.data.business_taxonomy import DEFAULT_MONTHLY_BUDGET_EUR
from app.models import Expense, ExpenseStatus
from app.utils.fiscal_year import financial_year_range, list_fy_months
from app.utils.time_period import utc_now


def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    last = monthrange(year, month)[1]
    start = datetime(year, month, 1, 0, 0, 0)
    end = datetime(year, month, last, 23, 59, 59, 999999)
    return start, end


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Inclusive UTC bounds for one calendar month."""
    month_start = datetime(year, month, 1, 0, 0, 0)
    last_day = calendar.monthrange(year, month)[1]
    month_end = datetime(year, month, last_day, 23, 59, 59)
    return month_start, month_end


def _approved_spend(
    db: Session, user_id: int, start: datetime, end: datetime, company_id: int = 1
) -> float:
    total = (
        db.query(func.coalesce(func.sum(Expense.bill_amount), 0))
        .filter(
            Expense.user_id == user_id,
            Expense.company_id == company_id,
            Expense.status == ExpenseStatus.APPROVED,
            Expense.bill_date >= start,
            Expense.bill_date <= end,
        )
        .scalar()
    )
    return float(total or 0)


def monthly_budget_utilisation(
    db: Session, user_id: int, company_id: int = 1
) -> Dict[str, Any]:
    """Current month spend vs €1M target; optional prior-month comparison (hidden in April)."""
    now = utc_now()
    target = DEFAULT_MONTHLY_BUDGET_EUR
    cur_start, cur_end = _month_range(now.year, now.month)
    current_actual = _approved_spend(db, user_id, cur_start, cur_end, company_id)
    current_util = round((current_actual / target) * 100, 1) if target else 0.0

    result: Dict[str, Any] = {
        "currency": "EUR",
        "budget_target": target,
        "month_label": now.strftime("%B %Y"),
        "current_month_actual": round(current_actual, 2),
        "current_utilisation_pct": current_util,
        "show_previous_month_comparison": now.month != 4,
    }

    if now.month == 4:
        return result

    if now.month == 1:
        py, pm = now.year - 1, 12
    else:
        py, pm = now.year, now.month - 1
    prev_start, prev_end = _month_range(py, pm)
    prev_actual = _approved_spend(db, user_id, prev_start, prev_end)
    prev_util = round((prev_actual / target) * 100, 1) if target else 0.0
    delta = round(current_util - prev_util, 1)
    if prev_actual > 0:
        expenditure_change = round(
            ((current_actual - prev_actual) / prev_actual) * 100, 1
        )
    elif current_actual > 0:
        expenditure_change = 100.0
    else:
        expenditure_change = 0.0
    result.update(
        {
            "previous_month_label": datetime(py, pm, 1).strftime("%B %Y"),
            "previous_month_actual": round(prev_actual, 2),
            "previous_utilisation_pct": prev_util,
            "utilisation_change_pct": delta,
            "expenditure_change_pct": expenditure_change,
        }
    )
    return result


def monthly_budget_grid(
    db: Session, user_id: int, financial_year: str
) -> Dict[str, Any]:
    """FY monthly budget grid (€1M target per month) vs approved spend."""
    financial_year_range(financial_year)  # validate
    months_meta = list_fy_months(financial_year)
    rows: List[Dict[str, Any]] = []
    grand_actual = 0.0
    target = DEFAULT_MONTHLY_BUDGET_EUR

    for m in months_meta:
        month_start, month_end = _month_bounds(m["year"], m["month"])
        actual_f = _approved_spend(db, user_id, month_start, month_end)
        grand_actual += actual_f
        util = round((actual_f / target) * 100, 1) if target else 0
        rows.append(
            {
                "month_label": m["label"],
                "year": m["year"],
                "month": m["month"],
                "budget_target": target,
                "actual": round(actual_f, 2),
                "utilisation_pct": util,
                "currency": "EUR",
            }
        )

    total_target = target * 12
    return {
        "financial_year": financial_year,
        "months": rows,
        "grand_total_actual": round(grand_actual, 2),
        "grand_total_budget": total_target,
        "grand_utilisation_pct": round((grand_actual / total_target) * 100, 1)
        if total_target
        else 0,
    }
