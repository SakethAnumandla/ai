"""Legacy Tesseract provider name — delegates to PaddleOCR (same OCRProcessor backend)."""
from app.intelligence.receipt.providers.base import OCRProviderKind
from app.intelligence.receipt.providers.paddleocr import PaddleOCRProvider


class TesseractOCRProvider(PaddleOCRProvider):
    """Deprecated: use PaddleOCRProvider. Kept for backward-compatible imports."""

    kind = OCRProviderKind.TESSERACT

    def extract(self, file_data, file_name, extension):
        result = super().extract(file_data, file_name, extension)
        result["ocr_provider"] = self.name
        return result
