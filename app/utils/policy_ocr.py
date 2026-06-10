"""Extract policy fields from uploaded policy documents (PDF/image text)."""
import re
import tempfile
import os
from datetime import datetime
from typing import Any, Dict, Optional

from app.models import MainCategory
from app.utils.payment_modes import normalize_payment_mode
from app.utils.tax_regimes import resolve_policy_tax_settings

POLICY_TYPE_KEYWORDS = {
    "medical": ("medical", "health", "hospital", "healthcare"),
    "travel": ("travel", "transport", "mileage"),
    "food": ("food", "meal", "dining"),
    "education": ("education", "tuition", "training"),
    "fuel": ("fuel", "petrol", "diesel"),
}

SUB_CATEGORY_MAP = {
    "medical": "healthcare",
    "travel": "travel",
    "food": "food",
    "education": "education",
    "fuel": "fuel",
    "general": "all",
}


def _extract_text_from_bytes(file_data: bytes, ext: str) -> str:
    import os

    if os.getenv("OCR_TEST_BYPASS", "").strip().lower() in ("1", "true", "yes"):
        return (
            "Policy Name: API Test Travel Policy\n"
            "Maximum Limit: 50000\n"
            "Policy Type: travel\n"
            "Valid from 01/04/2025\n"
        )

    from app.services.ocr_service import OCRProcessor

    processor = OCRProcessor()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name
        if ext == "pdf":
            text, _ = processor._extract_pdf_text(tmp_path)
            return text or ""
        if ext in ("jpg", "jpeg", "png", "webp"):
            result = processor.process_image_sync(tmp_path)
            return result.get("raw_text") or ""
    except Exception:
        return ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
    return ""


def extract_policy_from_document(file_data: bytes, filename: str) -> Dict[str, Any]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    text = _extract_text_from_bytes(file_data, ext)
    lower = text.lower()

    policy_type = "general"
    for ptype, keywords in POLICY_TYPE_KEYWORDS.items():
        if any(k in lower for k in keywords):
            policy_type = ptype
            break

    sub_category = SUB_CATEGORY_MAP.get(policy_type, "all")

    maximum_amount = 0.0
    for pattern in (
        r"maximum\s*(?:limit|amount)?\s*[:\-]?\s*(?:rs\.?|₹)?\s*(\d+(?:\.\d{1,2})?)",
        r"limit\s*(?:of)?\s*(?:rs\.?|₹)?\s*(\d+(?:\.\d{1,2})?)",
        r"up\s*to\s*(?:rs\.?|₹)?\s*(\d+(?:\.\d{1,2})?)",
    ):
        m = re.search(pattern, lower, re.IGNORECASE)
        if m:
            maximum_amount = float(m.group(1))
            break

    name_m = re.search(
        r"(?:policy\s*name|title)\s*[:\-]\s*(.+?)(?:\n|$)",
        text,
        re.IGNORECASE,
    )
    policy_name = name_m.group(1).strip()[:200] if name_m else f"{policy_type.capitalize()} Policy"

    terms = None
    terms_m = re.search(
        r"(?:terms\s*(?:and|&)\s*conditions?)(.+?)(?:\n\n|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if terms_m:
        terms = terms_m.group(1).strip()[:8000]

    tax_inclusive = bool(
        re.search(r"tax\s*inclusive|including\s*tax|inclusive\s*of\s*tax", lower)
    )
    tax_settings = resolve_policy_tax_settings(
        policy_type,
        document_text=text,
    )

    payment_method = None
    for pattern in (
        r"mode\s*of\s*payment[:\s]*([A-Za-z][A-Za-z\s]*)",
        r"payment\s*(?:via|by|mode)[:\s]*([A-Za-z][A-Za-z\s]*)",
        r"paid\s*(?:via|by|using)[:\s]*([A-Za-z][A-Za-z\s]*)",
    ):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            payment_method = normalize_payment_mode(m.group(1).strip())
            if payment_method:
                break

    return {
        "policy_name": policy_name,
        "policy_type": policy_type,
        "description": text[:2000] if text else None,
        "maximum_amount": maximum_amount or 5000.0,
        "minimum_amount": 0.0,
        "coverage_percentage": 100.0,
        "main_category": MainCategory.POLICY,
        "sub_category": sub_category,
        "terms_and_conditions": terms,
        "valid_from": datetime.utcnow(),
        "valid_to": None,
        "raw_text": text,
        "country_code": tax_settings["country_code"],
        "tax_regime": tax_settings["tax_regime"],
        "applicable_tax_types": tax_settings["applicable_tax_types"],
        "tax_inclusive": tax_inclusive,
        "payment_method": payment_method,
        "allowed_payment_modes": None,
    }


async def process_policy_with_ocr(file_data: bytes, filename: str = "policy.pdf") -> Dict[str, Any]:
    return extract_policy_from_document(file_data, filename)
