"""AWS Textract provider (future — stub falls back to PaddleOCR)."""
import logging
from typing import Any, Dict, Optional

from app.intelligence.receipt.providers.base import BaseOCRProvider, OCRProviderKind
from app.intelligence.receipt.providers.paddleocr import PaddleOCRProvider

logger = logging.getLogger(__name__)


class TextractOCRProvider(BaseOCRProvider):
    kind = OCRProviderKind.TEXTRACT

    def __init__(self, fallback: Optional[BaseOCRProvider] = None):
        self._fallback = fallback or PaddleOCRProvider()

    def extract(self, file_data: bytes, file_name: str, extension: str) -> Dict[str, Any]:
        logger.info("textract.not_implemented using paddleocr fallback")
        result = self._fallback.extract(file_data, file_name, extension)
        result["ocr_provider"] = f"{self.name}_fallback_paddleocr"
        return result
