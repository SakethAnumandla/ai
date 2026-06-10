"""GPT-4o Vision OCR provider (future — stub falls back to PaddleOCR)."""
import logging
from typing import Any, Dict, Optional

from app.intelligence.receipt.providers.base import BaseOCRProvider, OCRProviderKind
from app.intelligence.receipt.providers.paddleocr import PaddleOCRProvider

logger = logging.getLogger(__name__)


class GPT4VisionOCRProvider(BaseOCRProvider):
    """
    Placeholder for OpenAI vision receipt extraction.
    Set OPENAI_API_KEY and enable via OCR_PROVIDER=gpt4o_vision when implemented.
    """

    kind = OCRProviderKind.GPT4O_VISION

    def __init__(self, fallback: Optional[BaseOCRProvider] = None):
        self._fallback = fallback or PaddleOCRProvider()

    def extract(self, file_data: bytes, file_name: str, extension: str) -> Dict[str, Any]:
        logger.info("gpt4o_vision.not_implemented using paddleocr fallback")
        result = self._fallback.extract(file_data, file_name, extension)
        result["ocr_provider"] = f"{self.name}_fallback_paddleocr"
        return result
