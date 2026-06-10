"""expense.create.v1 argument enrichment from NL entities."""
from app.ai.tools.expense_create_enrichment import enrich_expense_create_arguments

COFFEE_MSG = (
    "I had coffee at cafe coffee day and the bill was 200 and add it to the expenses"
)


def test_enrich_maps_merchant_and_fixes_title():
    raw = {
        "bill_name": "Cafe Coffee Day And The Bill Was 200 And Add It To Expenses",
        "bill_amount": 200,
        "merchant": "Cafe Coffee Day",
    }
    out = enrich_expense_create_arguments(
        raw,
        user_message=COFFEE_MSG,
        workflow_slots={
            "vendor_name": "Cafe Coffee Day",
            "bill_name": "Coffee",
            "main_category": "food",
            "payment_method": "upi",
        },
    )
    assert out["vendor_name"] == "Cafe Coffee Day"
    assert out["bill_name"] == "Coffee"
    assert out["main_category"] == "food"
    assert out.get("sub_category") == "cafe"


def test_enrich_from_message_without_workflow():
    out = enrich_expense_create_arguments(
        {
            "bill_name": COFFEE_MSG,
            "bill_amount": 200,
        },
        user_message=COFFEE_MSG,
    )
    assert out["vendor_name"] == "Cafe Coffee Day"
    assert out["bill_name"] == "Coffee"
    assert out["main_category"] == "food"
