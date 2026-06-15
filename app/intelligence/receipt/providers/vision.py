"""GPT-4o vision receipt extraction provider."""
from typing import Any, Dict, List

from app.ai.vision_receipt import get_vision_extractor
from app.intelligence.receipt.providers.base import BaseOCRProvider, OCRProviderKind


class GPT4VisionOCRProvider(BaseOCRProvider):
    """OpenAI vision — primary receipt scanning backend."""

    kind = OCRProviderKind.GPT4O_VISION

    def __init__(self) -> None:
        self._vision = get_vision_extractor()

    def extract(self, file_data: bytes, file_name: str, extension: str) -> Dict[str, Any]:
        raw = self._vision.extract_sync(file_data, file_name, extension)
        raw["ocr_provider"] = self.name
        return self.normalize(raw)

    def extract_pages(
        self, file_data: bytes, file_name: str, extension: str
    ) -> List[Dict[str, Any]]:
        ext = extension.lower().lstrip(".")
        raw = self._vision.extract_sync(file_data, file_name, ext)
        raw["ocr_provider"] = self.name
        page_extractions = raw.get("page_extractions") or []
        if ext == "pdf" and page_extractions:
            return [
                self.normalize({**p, "ocr_provider": self.name, "_legacy": p})
                for p in page_extractions
            ]
        return [self.normalize(raw)]
