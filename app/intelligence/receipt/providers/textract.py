"""AWS Textract provider — delegates to LLM vision until Textract is configured."""
from app.intelligence.receipt.providers.vision import GPT4VisionOCRProvider


class TextractOCRProvider(GPT4VisionOCRProvider):
    kind = GPT4VisionOCRProvider.kind
