"""OCR provider abstraction — swap engines without changing the receipt pipeline."""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional


class OCRProviderKind(str, Enum):
    PADDLEOCR = "paddleocr"
    TESSERACT = "tesseract"  # legacy alias → paddleocr
    GPT4O_VISION = "gpt4o_vision"
    TEXTRACT = "textract"
    GOOGLE_VISION = "google_vision"


class BaseOCRProvider(ABC):
    """Unified contract for all OCR backends."""

    kind: OCRProviderKind

    @property
    def name(self) -> str:
        return self.kind.value

    @abstractmethod
    def extract(self, file_data: bytes, file_name: str, extension: str) -> Dict[str, Any]:
        """Return normalized receipt dict (see OCRProviderRegistry.normalize)."""

    def extract_pages(
        self, file_data: bytes, file_name: str, extension: str
    ) -> List[Dict[str, Any]]:
        """Per-page extraction; default single-page wrapper."""
        return [self.extract(file_data, file_name, extension)]

    @classmethod
    def normalize(cls, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Map provider output to receipt entity field names."""
        legacy = raw.get("_legacy") or raw
        return {
            "merchant": raw.get("merchant")
            or legacy.get("vendor_name")
            or legacy.get("restaurant_name"),
            "vendor_gst": raw.get("vendor_gst") or legacy.get("vendor_gst"),
            "invoice_date": raw.get("invoice_date") or legacy.get("bill_date"),
            "invoice_id": raw.get("invoice_id") or legacy.get("bill_number"),
            "subtotal": raw.get("subtotal") or legacy.get("subtotal"),
            "total": raw.get("total") or legacy.get("total_amount"),
            "tax": raw.get("tax") or legacy.get("tax_amount"),
            "currency": raw.get("currency") or legacy.get("currency") or "INR",
            "payment_method": raw.get("payment_method") or legacy.get("payment_method"),
            "raw_text": raw.get("raw_text") or legacy.get("raw_text"),
            "confidence_score": raw.get("confidence_score")
            or legacy.get("confidence_score")
            or 0.5,
            "tax_breakdown": raw.get("tax_breakdown") or legacy.get("tax_breakdown"),
            "items_list": raw.get("items_list") or legacy.get("items_list"),
            "pdf_page_count": raw.get("pdf_page_count"),
            "page_extractions": raw.get("page_extractions"),
            "ocr_provider": raw.get("ocr_provider"),
            "_legacy": legacy,
        }
