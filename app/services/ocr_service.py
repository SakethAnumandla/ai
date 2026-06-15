"""Bill/receipt extraction — delegates to OpenAI vision (legacy module name retained)."""
from __future__ import annotations

import os
from typing import Any, Dict

from app.ai.vision_receipt import get_vision_extractor


class OCRProcessor:
    """Facade for receipt extraction. All paths use LLM vision scanning."""

    def __init__(self) -> None:
        self._vision = get_vision_extractor()

    def _read_file(self, file_path: str) -> bytes:
        with open(file_path, "rb") as f:
            return f.read()

    def process_image_sync(self, image_path: str) -> Dict[str, Any]:
        ext = image_path.rsplit(".", 1)[-1].lower()
        data = self._read_file(image_path)
        return self._vision.extract_sync(data, os.path.basename(image_path), ext)

    def process_pdf_sync(self, pdf_path: str) -> Dict[str, Any]:
        data = self._read_file(pdf_path)
        return self._vision.extract_sync(data, os.path.basename(pdf_path), "pdf")

    async def process_image(self, image_path: str) -> Dict[str, Any]:
        return self.process_image_sync(image_path)

    async def process_pdf(self, pdf_path: str) -> Dict[str, Any]:
        return self.process_pdf_sync(pdf_path)

    async def extract_bill_data(self, file_path: str, file_type: str) -> Dict[str, Any]:
        return self.extract_bill_data_sync(file_path, file_type)

    def extract_bill_data_sync(self, file_path: str, file_type: str) -> Dict[str, Any]:
        data = self._read_file(file_path)
        return self._vision.extract_sync(
            data,
            os.path.basename(file_path),
            file_type.lower(),
        )
