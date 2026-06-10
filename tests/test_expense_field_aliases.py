"""LLM field aliases must survive normalization before schema validation."""
from app.services.expense_enrichment_service import apply_field_aliases
from app.ai.tools.argument_normalizer import normalize_tool_arguments


def test_apply_field_aliases_maps_llm_shape():
    raw = {
        "title": "Expense",
        "amount": 200,
        "vendor": "Uber",
        "category": "travel",
        "subcategory": "uber",
        "payment_method": "credit_card",
        "tags": ["ride", "travel"],
    }
    out = apply_field_aliases(raw)
    assert out["bill_name"] == "Expense"
    assert out["bill_amount"] == 200
    assert out["vendor_name"] == "Uber"
    assert out["main_category"] == "travel"
    assert out["sub_category"] == "uber"
    assert out["hashtags"] == ["ride", "travel"]


def test_normalize_preserves_mapped_amount():
    out = normalize_tool_arguments({"title": "Coffee", "amount": "200"})
    assert out["bill_name"] == "Coffee"
    assert out["bill_amount"] == 200
