"""Expense extraction and enrichment pipeline."""
import pytest

from app.ai.expense_extraction import (
    ExpenseExtractionResult,
    ExpenseExtractionService,
    user_description_from_message,
)
from app.ai.tools.expense_create_enrichment import enrich_expense_create_arguments
from app.ai.workflow.entity_extractor import ExpenseEntityExtractor

KOI_MSG = (
    "Yesterday I went to Koi and Co, had coffee, the bill was 200 and I paid using UPI"
)


def test_vendor_extracts_went_to_koi():
    entities = ExpenseEntityExtractor().extract(KOI_MSG)
    assert entities.bill_amount == 200
    assert entities.vendor_name == "Koi And Co"
    assert entities.payment_method == "upi"


FLAMINGO_MSG = (
    "I had coffee at Flamingo Cafe and the coffee bill was 100 and I paid using UPI"
)


def test_enrich_uses_source_utterance_on_confirm():
    out = enrich_expense_create_arguments(
        {"bill_name": "Flamingo Cafe And The Coffee Bill Was 100 And I P", "bill_amount": 100},
        user_message="yes",
        source_utterance=FLAMINGO_MSG,
    )
    assert out["vendor_name"] == "Flamingo Cafe"
    assert out["payment_method"] == "upi"
    assert out["bill_name"] == "Coffee"
    assert out["main_category"] == "food"


def test_user_description_from_message():
    desc = user_description_from_message(KOI_MSG)
    assert desc is not None
    assert "Koi" in desc or "coffee" in desc.lower()


def test_extraction_result_to_create_arguments():
    result = ExpenseExtractionResult(
        amount=200,
        vendor="Koi And Co",
        category="food",
        subcategory="cafe",
        payment_method="upi",
        description="Coffee at Koi And Co",
        tags=["coffee", "cafe"],
    )
    args = result.to_create_arguments()
    assert args["bill_amount"] == 200
    assert args["vendor_name"] == "Koi And Co"
    assert args["main_category"] == "food"
    assert args["sub_category"] == "cafe"
    assert args["payment_method"] == "upi"
    assert args["description"] == "Coffee at Koi And Co"
    assert args["hashtags"] == ["coffee", "cafe"]


def test_enrich_passes_description_and_vendor():
    sync = ExpenseExtractionService().extract_sync(KOI_MSG)
    out = enrich_expense_create_arguments(
        {"bill_name": KOI_MSG, "bill_amount": 200},
        user_message=KOI_MSG,
        extracted=sync.to_create_arguments(),
    )
    assert out["vendor_name"] == "Koi And Co"
    assert out["payment_method"] == "upi"
    assert out.get("description")
    assert out["bill_name"] != KOI_MSG or len(out["bill_name"].split()) <= 6
