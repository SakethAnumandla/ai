"""PaddleOCR provider (default)."""
import os
import tempfile
from typing import Any, Dict, List, Optional

from app.intelligence.receipt.providers.base import BaseOCRProvider, OCRProviderKind
from app.services.ocr_service import OCRProcessor


class PaddleOCRProvider(BaseOCRProvider):
    kind = OCRProviderKind.PADDLEOCR

    def __init__(self, processor: Optional[OCRProcessor] = None):
        self._processor = processor or OCRProcessor()

    def extract(self, file_data: bytes, file_name: str, extension: str) -> Dict[str, Any]:
        ext = extension.lower().lstrip(".")
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                tmp.write(file_data)
                tmp_path = tmp.name
            if ext == "pdf":
                raw = self._processor.process_pdf_sync(tmp_path)
            else:
                raw = self._processor.process_image_sync(tmp_path)
            raw["ocr_provider"] = self.name
            return self.normalize(raw)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def extract_pages(self, file_data: bytes, file_name: str, extension: str) -> List[Dict[str, Any]]:
        ext = extension.lower().lstrip(".")
        if ext != "pdf":
            return [self.extract(file_data, file_name, extension)]

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(file_data)
                tmp_path = tmp.name
            from app.intelligence.receipt.pdf_aggregator import PdfPageExtractor

            pages = PdfPageExtractor(self._processor).extract_per_page(tmp_path)
            return [self.normalize({**p, "ocr_provider": self.name}) for p in pages]
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
