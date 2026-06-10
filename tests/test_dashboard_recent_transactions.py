"""Recent transactions list helpers."""
from unittest.mock import MagicMock

from app.models import ExpenseStatus
from app.utils.dashboard_queries import (
    expense_status_display,
    merge_latest_upload,
    serialize_recent_transaction,
)


def test_expense_status_display_maps_legacy_pending_to_submitted():
    assert expense_status_display(ExpenseStatus.PENDING) == "submitted"
    assert expense_status_display(ExpenseStatus.SUBMITTED) == "submitted"
    assert expense_status_display(ExpenseStatus.DRAFT) == "draft"


def test_serialize_recent_transaction_includes_status():
    expense = MagicMock()
    expense.id = 7
    expense.bill_name = "Coffee"
    expense.bill_amount = 120.0
    expense.bill_date = None
    expense.transaction_type.value = "expense"
    expense.main_category.value = "food"
    expense.sub_category = "cafe"
    expense.vendor_name = "Blue Tokai"
    expense.status = ExpenseStatus.SUBMITTED
    expense.upload_method.value = "ocr"
    expense.created_at = None
    expense.updated_at = None

    row = serialize_recent_transaction(expense)
    assert row["status"] == "submitted"
    assert row["upload_method"] == "ocr"
    assert row["sub_category"] == "cafe"


def test_merge_latest_upload_prepends_when_missing():
    existing = [{"id": 1, "bill_name": "Old"}]
    latest = MagicMock()
    latest.id = 2
    latest.bill_name = "New upload"
    latest.bill_amount = 50.0
    latest.bill_date = None
    latest.transaction_type.value = "expense"
    latest.main_category.value = "food"
    latest.sub_category = None
    latest.vendor_name = None
    latest.status = ExpenseStatus.DRAFT
    latest.upload_method.value = "ocr"
    latest.created_at = None
    latest.updated_at = None

    merged = merge_latest_upload(existing, latest, limit=10)
    assert len(merged) == 2
    assert merged[0]["id"] == 2
    assert merged[0]["is_latest_upload"] is True
    assert merged[0]["status"] == "draft"


def test_merge_latest_upload_does_not_duplicate():
    existing = [{"id": 1, "bill_name": "Only"}]
    latest = MagicMock()
    latest.id = 1

    merged = merge_latest_upload(existing, latest, limit=10)
    assert merged == existing
