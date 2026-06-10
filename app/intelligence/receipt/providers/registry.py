"""OCR provider registry and factory."""
from typing import Dict, Type

from app.config import settings
from app.intelligence.receipt.providers.base import BaseOCRProvider, OCRProviderKind
from app.intelligence.receipt.providers.google_vision import GoogleVisionOCRProvider
from app.intelligence.receipt.providers.paddleocr import PaddleOCRProvider
from app.intelligence.receipt.providers.textract import TextractOCRProvider
from app.intelligence.receipt.providers.vision import GPT4VisionOCRProvider

_PROVIDERS: Dict[OCRProviderKind, Type[BaseOCRProvider]] = {
    OCRProviderKind.PADDLEOCR: PaddleOCRProvider,
    OCRProviderKind.TESSERACT: PaddleOCRProvider,
    OCRProviderKind.GPT4O_VISION: GPT4VisionOCRProvider,
    OCRProviderKind.TEXTRACT: TextractOCRProvider,
    OCRProviderKind.GOOGLE_VISION: GoogleVisionOCRProvider,
}

_ALIASES = {
    "paddle": OCRProviderKind.PADDLEOCR,
    "paddle_ocr": OCRProviderKind.PADDLEOCR,
}


def get_ocr_provider(kind: str | None = None) -> BaseOCRProvider:
    """Resolve provider from settings.ocr_provider or explicit kind."""
    key = (kind or settings.ocr_provider or "paddleocr").lower().replace("-", "_")
    enum_key = _ALIASES.get(key)
    if enum_key is None:
        try:
            enum_key = OCRProviderKind(key)
        except ValueError:
            enum_key = OCRProviderKind.PADDLEOCR
    cls = _PROVIDERS.get(enum_key, PaddleOCRProvider)
    return cls()


def get_default_ocr_provider() -> BaseOCRProvider:
    return get_ocr_provider()
