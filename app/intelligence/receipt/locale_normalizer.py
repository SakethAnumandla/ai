"""Multi-language OCR normalization — future extension point."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class NormalizedReceiptLocale:
    locale: str
    currency: str
    normalized: Dict[str, Any]


class BaseLocaleNormalizer(ABC):
    """
    Normalize multilingual OCR output to canonical fields.

    Future: locale-aware dates, decimal separators, currency symbols.
    """

    @abstractmethod
    def detect_locale(self, raw_text: str) -> str:
        ...

    @abstractmethod
    def normalize(
        self,
        fields: Dict[str, Any],
        *,
        raw_text: Optional[str] = None,
        hint_locale: Optional[str] = None,
    ) -> NormalizedReceiptLocale:
        ...


class PassThroughLocaleNormalizer(BaseLocaleNormalizer):
    """Default until multi-language packs are implemented."""

    def detect_locale(self, raw_text: str) -> str:
        return "en_IN"

    def normalize(
        self,
        fields: Dict[str, Any],
        *,
        raw_text: Optional[str] = None,
        hint_locale: Optional[str] = None,
    ) -> NormalizedReceiptLocale:
        locale = hint_locale or "en_IN"
        currency = fields.get("currency") or "INR"
        return NormalizedReceiptLocale(locale=locale, currency=currency, normalized=dict(fields))


def get_locale_normalizer() -> BaseLocaleNormalizer:
    from app.config import settings

    if getattr(settings, "ocr_locale_normalization_enabled", False):
        # Future: return BabelLocaleNormalizer()
        pass
    return PassThroughLocaleNormalizer()
