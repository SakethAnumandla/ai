"""Workflow slot parsing and draft summary."""
import pytest

from app.ai.workflow.draft_summary import format_draft_summary
from app.ai.workflow.slot_parser import (
    is_payment_method_text,
    is_workflow_slot_message,
    parse_slot_updates,
    sanitize_sub_category,
)


def test_parse_sub_category_maps_biryani_to_restaurant():
    assert parse_slot_updates("mention sub category as biryani") == {
        "sub_category": "restaurant",
        "sub_category_raw": "Biryani",
    }


def test_sanitize_biryani_for_food():
    assert sanitize_sub_category("food", "Biryani") == "restaurant"


def test_upi_is_payment_not_sub_category():
    assert is_payment_method_text("UPI")
    assert is_payment_method_text("I paid using UPI")
    assert sanitize_sub_category("food", "Upi", bill_name="Lunch") == "restaurant"


def test_sanitize_infers_restaurant_from_lunch_vendor():
    assert (
        sanitize_sub_category(
            "food",
            None,
            vendor_name="Bawarchi Restaurant",
            bill_name="Lunch",
        )
        == "restaurant"
    )


def test_is_workflow_slot_message():
    assert is_workflow_slot_message("mention sub category as biryani")
    assert not is_workflow_slot_message("hello")


def test_format_draft_summary():
    text = format_draft_summary(
        {
            "vendor_name": "Bawarchi",
            "bill_amount": 500,
            "main_category": "food",
            "sub_category": "restaurant",
            "sub_category_raw": "Biryani",
        }
    )
    assert "Bawarchi" in text
    assert "₹500" in text
    assert "restaurant" in text.lower() or "Biryani" in text
    assert "save this expense" in text.lower()
