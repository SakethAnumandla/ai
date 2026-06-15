"""Legacy Tesseract provider name — delegates to LLM vision."""
from app.intelligence.receipt.providers.vision import GPT4VisionOCRProvider


class TesseractOCRProvider(GPT4VisionOCRProvider):
    """Deprecated alias — vision scanning is used."""

    kind = GPT4VisionOCRProvider.kind
