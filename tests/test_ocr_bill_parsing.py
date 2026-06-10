"""OCR bill amount extraction — restaurant receipts and failure modes."""
from app.models import MainCategory, TransactionType
from app.services.ocr_draft_service import build_prefill_dict, resolve_prefill_bill_amount
from app.services.ocr_service import OCRProcessor
from app.utils.ocr_categories import resolve_classification
from app.utils.ocr_prefill import enrich_prefill_dict

SRIGANDA_RECEIPT = """
Bhagini
Sriganda Palace
GST No 29ADDPR8125K1Z2
RECEIPT
Name: Siva Shankar
Invoice No: 7767
Table #37
Date: 16 May 2024
Time: 21:18
Item Price Qty Total
Mutton biriyani 400 4 1600
Tandoori Roti 30 5 150
Chilly chicken 250 2 500
Chicken pepper 250 3 750
Sub-Total 3000
CGST 2.5% 75
SGST 2.5% 75
Payment Mode: Cash
Total
3150
Time: 21:18
"""


def test_sriganda_receipt_parses_grand_total():
    p = OCRProcessor()
    parsed = p._parse_bill_text(SRIGANDA_RECEIPT)
    assert parsed["subtotal"] == 3000.0
    assert parsed["total_amount"] == 3150.0
    assert parsed["tax_amount"] == 150.0
    assert len(parsed["items_list"]) == 4

    prefill = build_prefill_dict(
        parsed,
        "receipt.jpg",
        1,
        MainCategory.MISCELLANEOUS,
        None,
        TransactionType.EXPENSE,
    )
    assert prefill["bill_amount"] == 3150.0
    assert prefill["amount_needs_review"] is False


def test_invoice_number_not_used_as_total():
    p = OCRProcessor()
    parsed = p._parse_bill_text("Invoice No 7767\nTable #37\n1\n1")
    assert parsed.get("total_amount") != 7767.0


def test_no_placeholder_one_euro_on_empty_ocr():
    amount, needs_review = resolve_prefill_bill_amount({})
    assert amount == 0.0
    assert needs_review is True


def test_sriganda_vendor_and_category_prefill():
    p = OCRProcessor()
    parsed = p._parse_bill_text(SRIGANDA_RECEIPT)
    assert "Palace" in (parsed.get("vendor_name") or "")
    assert "Bhagini" in (parsed.get("vendor_name") or "")

    tx, mc, sub = resolve_classification(parsed, parsed.get("raw_text"))
    prefill = build_prefill_dict(parsed, "receipt.jpg", 1, mc, sub, tx)
    prefill = enrich_prefill_dict(prefill)
    assert prefill["vendor_name"]
    assert "Palace" in prefill["vendor_name"] and "Bhagini" in prefill["vendor_name"]
    assert prefill["main_category"] == "meals_entertainment"
    assert prefill.get("sub_category")
    assert prefill.get("payment_method") == "cash"
    assert prefill.get("amount_excl_gst") == 3000.0


BLURRY_SRIGANDA_RECEIPT = """
Bhagini
Sriganda Pa1ace
GST No 29ADDPR8125K1Z2
RECEIPT
Name: Siva Shankar
Invoice No: 7767
Tab1e #37
Date: 16 May 2024
Item Price Qty Tota1
Mutton biriyani 400 4 1600
Tandoori Roti 30 5 150
Chi11y chicken 250 2 500
Chicken pepper 250 3 750
Sub-Tota1 3000
CG5T 2.5% 75
5GST 2.5% 75
Payment Mode: Ca5h
Tota1
315O
"""


def test_blurry_ocr_text_normalization_and_parse():
    p = OCRProcessor()
    parsed = p._parse_bill_text(BLURRY_SRIGANDA_RECEIPT)
    assert parsed["subtotal"] == 3000.0
    assert parsed["total_amount"] == 3150.0
    assert parsed.get("payment_method") == "cash" or "cash" in str(
        parsed.get("payment_method", "")
    ).lower()


def test_merge_parsed_candidates_picks_best_fields():
    p = OCRProcessor()
    clean = p._parse_bill_text(SRIGANDA_RECEIPT)
    noisy = p._parse_bill_text(BLURRY_SRIGANDA_RECEIPT)
    noisy["vendor_name"] = None
    merged = p._merge_parsed_candidates([noisy, clean])
    assert merged is not None
    assert merged["total_amount"] == 3150.0
    assert merged["subtotal"] == 3000.0
    assert "Palace" in (merged.get("vendor_name") or "")


def test_merge_variant_texts_combines_passes():
    from app.services.paddle_ocr_engine import merge_variant_texts

    pass_a = "Bhagini\nSriganda Palace\nSub-Total 3000"
    pass_b = "GST No 29ADDPR8125K1Z2\nCGST 2.5% 75\nTotal 3150"
    merged = merge_variant_texts([pass_a, pass_b])
    assert "Bhagini" in merged
    assert "3150" in merged
    assert "CGST" in merged or "75" in merged


BHAGINI_OCR_RAW = """
Bhagini
Sriganda Palace
Price
Qty
Total
Item
Muttonbiriyani
400
4
1600
TandooriRoti
30
5
150
Chilly chicken
250
500
2
Chicken pepper
250
3
750
Sub-Total:
3000
CGST:
2.5%
75
SGST:
2.5%
75
Mode:Cash
Total:
3150
Time:21:18
"""


def test_bhagini_ocr_raw_with_table_header_parses_correctly():
    p = OCRProcessor()
    parsed = p._parse_bill_text(BHAGINI_OCR_RAW)
    assert parsed["subtotal"] == 3000.0
    assert parsed["total_amount"] == 3150.0
    assert parsed["tax_amount"] == 150.0
    assert parsed["tax_breakdown"].get("cgst") == 75.0
    assert parsed["tax_breakdown"].get("sgst") == 75.0


def test_items_sum_used_when_total_is_one():
    extracted = {
        "total_amount": 1.0,
        "subtotal": 1.0,
        "items_list": [
            {"name": "Mutton biriyani", "price": 1600.0},
            {"name": "Tandoori Roti", "price": 150.0},
        ],
        "tax_amount": 75.0,
    }
    amount, needs_review = resolve_prefill_bill_amount(extracted)
    assert amount >= 1600.0
    assert amount != 1.0


def test_unreadable_empty_ocr_quality():
    from app.utils.ocr_quality import assess_ocr_scan_quality, ensure_ocr_readable
    import pytest

    quality = assess_ocr_scan_quality({"raw_text": "", "confidence_score": 0.0})
    assert quality["quality"] == "unreadable"
    assert quality["retake_recommended"] is True
    assert "Couldn't read receipt" in (quality.get("user_message") or "")

    with pytest.raises(Exception) as exc_info:
        ensure_ocr_readable({"raw_text": "x", "confidence_score": 0.0})
    assert "Couldn't read receipt" in str(exc_info.value)


def test_blurry_noise_fails_when_unparseable():
    from app.utils.ocr_quality import assess_ocr_scan_quality

    quality = assess_ocr_scan_quality(
        {
            "raw_text": "abc\n123",
            "confidence_score": 5.0,
            "ocr_engine_confidence": 0.1,
            "image_blurry": True,
            "total_amount": None,
        }
    )
    assert quality["quality"] == "unreadable"
    assert quality["retake_recommended"] is True
