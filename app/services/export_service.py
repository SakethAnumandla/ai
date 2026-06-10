"""Expense export by financial year or time period."""
from __future__ import annotations

import csv
import logging
from io import StringIO
from typing import Any, Dict, List, Literal

from sqlalchemy.orm import Session

from app.models import Expense, ExpenseStatus
from app.utils.fiscal_year import financial_year_range
from app.utils.time_period import ResolvedTimePeriod, apply_bill_date_filter

logger = logging.getLogger(__name__)

GroupBy = Literal["month", "category"]


def _enum_val(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def expense_fy_export_row(expense: Expense, fy: str) -> dict:
    return {
        "expense_id": f"EXP-{expense.id:04d}",
        "bill_name": expense.bill_name,
        "bill_date": expense.bill_date.isoformat() if expense.bill_date else None,
        "financial_year": expense.financial_year or fy,
        "main_category": expense.main_category.value if expense.main_category else None,
        "sub_category": expense.sub_category,
        "line_item": expense.line_item,
        "vendor_name": expense.vendor_name,
        "amount_excl_gst": expense.amount_excl_gst,
        "gst_rate_pct": expense.gst_rate_pct,
        "gst_amount": expense.gst_amount,
        "total_amount": expense.bill_amount,
        "currency_code": expense.currency_code or "EUR",
        "itc_eligible": expense.itc_eligible,
        "payment_method": expense.payment_method.value if expense.payment_method else None,
        "hashtags": expense.hashtags or [],
        "status": expense.status.value,
        "approved_at": expense.approved_at.isoformat() if expense.approved_at else None,
    }


def expense_period_export_row(expense: Expense) -> dict:
    return {
        "id": expense.id,
        "bill_name": expense.bill_name,
        "bill_amount": expense.bill_amount,
        "bill_date": expense.bill_date.isoformat() if expense.bill_date else None,
        "transaction_type": _enum_val(expense.transaction_type),
        "category": _enum_val(expense.main_category),
        "sub_category": expense.sub_category,
        "line_item": expense.line_item,
        "financial_year": expense.financial_year,
        "status": _enum_val(expense.status),
        "description": expense.description,
        "vendor_name": expense.vendor_name,
        "payment_method": (
            _enum_val(expense.payment_method) if expense.payment_method else None
        ),
        "currency_code": expense.currency_code,
        "created_at": expense.created_at.isoformat() if expense.created_at else None,
        "approved_at": expense.approved_at.isoformat() if expense.approved_at else None,
    }


class ExportService:
    """Approved expense exports grouped by FY or filtered period."""

    def __init__(self, db: Session):
        self.db = db

    def export_by_financial_year(
        self,
        user_id: int,
        financial_year: str,
        group_by: GroupBy = "month",
    ) -> Dict[str, Any]:
        start_dt, end_dt = financial_year_range(financial_year)
        expenses = (
            self.db.query(Expense)
            .filter(
                Expense.user_id == user_id,
                Expense.status == ExpenseStatus.APPROVED,
                Expense.bill_date >= start_dt,
                Expense.bill_date <= end_dt,
            )
            .order_by(Expense.bill_date)
            .all()
        )

        buckets: Dict[str, List[dict]] = {}
        for expense in expenses:
            if group_by == "category":
                key = expense.main_category.value if expense.main_category else "unknown"
            else:
                bd = expense.bill_date
                key = f"{bd.year}-{bd.month:02d}" if bd else "unknown"
            buckets.setdefault(key, []).append(
                expense_fy_export_row(expense, financial_year)
            )

        return {
            "financial_year": financial_year,
            "group_by": group_by,
            "groups": buckets,
        }

    def list_approved_for_period(
        self, user_id: int, resolved: ResolvedTimePeriod
    ) -> List[dict]:
        q = self.db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.status == ExpenseStatus.APPROVED,
        )
        q = apply_bill_date_filter(q, Expense, resolved)
        rows: List[dict] = []
        for expense in q.all():
            try:
                rows.append(expense_period_export_row(expense))
            except Exception as exc:
                logger.warning("export_row_skip expense_id=%s: %s", expense.id, exc)
        return rows

    @staticmethod
    def csv_from_rows(rows: List[dict], filename: str) -> tuple[str, str]:
        """Return (csv_content, content_disposition_header)."""
        output = StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        disposition = f'attachment; filename="{filename}"'
        return output.getvalue(), disposition
