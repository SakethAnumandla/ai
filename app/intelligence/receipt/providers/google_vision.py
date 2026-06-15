"""Google Cloud Vision provider — delegates to LLM vision until configured."""
from app.intelligence.receipt.providers.vision import GPT4VisionOCRProvider


class GoogleVisionOCRProvider(GPT4VisionOCRProvider):
    kind = GPT4VisionOCRProvider.kind
