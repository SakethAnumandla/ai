"""Apply business taxonomy + FY fields to Expense rows."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.models import Expense, MainCategory
from app.utils.fiscal_year import financial_year_label, validate_bill_date


def apply_business_fields(
    expense: Expense,
    *,
    main_category: Optional[Any] = None,
    sub_category: Optional[str] = None,
    line_item: Optional[str] = None,
    bill_date: Optional[datetime] = None,
    amount_excl_gst: Optional[float] = None,
    gst_rate_pct: Optional[float] = None,
    gst_amount: Optional[float] = None,
    itc_eligible: Optional[bool] = None,
    currency_code: Optional[str] = None,
    vendor_name: Optional[str] = None,
) -> None:
    if main_category is not None:
        if isinstance(main_category, MainCategory):
            expense.main_category = main_category
        else:
            try:
                expense.main_category = MainCategory(str(main_category).lower())
            except ValueError:
                pass
    if sub_category is not None:
        expense.sub_category = sub_category
    if line_item is not None:
        expense.line_item = line_item
    if vendor_name is not None:
        expense.vendor_name = vendor_name
    if bill_date is not None:
        expense.bill_date = bill_date
        try:
            d = bill_date.date() if isinstance(bill_date, datetime) else bill_date
            expense.financial_year = validate_bill_date(d)
        except ValueError:
            expense.financial_year = financial_year_label(
                bill_date.date() if isinstance(bill_date, datetime) else bill_date
            )
    if amount_excl_gst is not None:
        expense.amount_excl_gst = amount_excl_gst
    if gst_rate_pct is not None:
        expense.gst_rate_pct = gst_rate_pct
    if gst_amount is not None:
        expense.gst_amount = gst_amount
    if itc_eligible is not None:
        expense.itc_eligible = itc_eligible
    if currency_code:
        expense.currency_code = currency_code
