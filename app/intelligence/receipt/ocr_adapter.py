"""Backward-compatible OCR adapter — delegates to provider registry."""
from typing import Any, Dict

from app.intelligence.receipt.providers import get_default_ocr_provider
from app.intelligence.receipt.providers.base import BaseOCRProvider


def get_default_ocr_adapter() -> BaseOCRProvider:
    return get_default_ocr_provider()
