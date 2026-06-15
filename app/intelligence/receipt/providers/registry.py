"""OCR provider registry — LLM vision is the default."""
from typing import Dict, Type

from app.config import settings
from app.intelligence.receipt.providers.base import BaseOCRProvider, OCRProviderKind
from app.intelligence.receipt.providers.vision import GPT4VisionOCRProvider

_PROVIDERS: Dict[OCRProviderKind, Type[BaseOCRProvider]] = {
    OCRProviderKind.GPT4O_VISION: GPT4VisionOCRProvider,
    OCRProviderKind.PADDLEOCR: GPT4VisionOCRProvider,
    OCRProviderKind.TESSERACT: GPT4VisionOCRProvider,
    OCRProviderKind.TEXTRACT: GPT4VisionOCRProvider,
    OCRProviderKind.GOOGLE_VISION: GPT4VisionOCRProvider,
}

_ALIASES = {
    "paddle": OCRProviderKind.GPT4O_VISION,
    "paddle_ocr": OCRProviderKind.GPT4O_VISION,
    "paddleocr": OCRProviderKind.GPT4O_VISION,
    "tesseract": OCRProviderKind.GPT4O_VISION,
    "vision": OCRProviderKind.GPT4O_VISION,
    "llm": OCRProviderKind.GPT4O_VISION,
}


def get_ocr_provider(kind: str | None = None) -> BaseOCRProvider:
    """Resolve provider from settings.ocr_provider or explicit kind."""
    key = (kind or settings.ocr_provider or "gpt4o_vision").lower().replace("-", "_")
    enum_key = _ALIASES.get(key)
    if enum_key is None:
        try:
            enum_key = OCRProviderKind(key)
        except ValueError:
            enum_key = OCRProviderKind.GPT4O_VISION
    cls = _PROVIDERS.get(enum_key, GPT4VisionOCRProvider)
    return cls()


def get_default_ocr_provider() -> BaseOCRProvider:
    return get_ocr_provider()
