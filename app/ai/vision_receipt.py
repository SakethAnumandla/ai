"""Receipt / invoice extraction via OpenAI vision (replaces PaddleOCR / Tesseract)."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

MAX_VISION_PAGES = 8
MAX_IMAGE_DIMENSION = 2048
JPEG_QUALITY = 85

ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "gif"})

_EXTRACTION_SYSTEM = """You extract structured data from expense receipts, invoices, and bills.
Read every attached page carefully (images or PDF pages).

Return a single JSON object with these keys:
- vendor_name (string|null): merchant / business name
- restaurant_name (string|null): venue name if different from vendor
- bill_number (string|null): invoice or receipt number
- bill_date (string|null): ISO date YYYY-MM-DD when possible
- total_amount (number|null): final amount paid (grand total)
- subtotal (number|null)
- tax_amount (number|null)
- tax_breakdown (object|null): e.g. {"cgst": 25.0, "sgst": 25.0, "igst": 0}
- payment_method (string|null): cash|upi|card|credit_card|debit_card|net_banking|wallet
- currency (string): ISO code, default INR
- items_list (array): [{name, price, qty}] line items when visible
- raw_text (string): full transcription of visible text
- confidence_score (number): 0.0–1.0 how confident you are in total_amount and vendor_name
- description (string|null): short summary
- main_category_hint (string|null): food|travel|fuel|utilities|shopping|miscellaneous
- page_extractions (array|null): for multi-page PDFs only — one object per page with the same field keys

Rules:
- Prefer grand total / amount payable over subtotals.
- Use null for fields you cannot read; do not invent amounts.
- If the document is unreadable, set confidence_score below 0.3 and raw_text to "".
"""

_extractor: Optional["VisionReceiptExtractor"] = None


def get_vision_extractor() -> "VisionReceiptExtractor":
    global _extractor
    if _extractor is None:
        _extractor = VisionReceiptExtractor()
    return _extractor


def _extract_pdf_embedded_text(data: bytes, max_chars: int = 14000) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        chunks: List[str] = []
        for page in reader.pages[:MAX_VISION_PAGES]:
            t = (page.extract_text() or "").strip()
            if t:
                chunks.append(t)
        full = "\n\n".join(chunks).strip()
        if len(full) > max_chars:
            return full[:max_chars] + "\n…[truncated]"
        return full
    except Exception as exc:
        logger.debug("vision.pdf_text_failed: %s", exc)
        return ""


def _guess_image_mime(head: bytes, ext: str) -> str:
    if len(head) >= 3 and head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(head) >= 8 and head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    return "image/jpeg"


def _compress_image_bytes(data: bytes, ext: str) -> Tuple[bytes, str]:
    """Downscale large images to stay within vision API limits."""
    try:
        from PIL import Image
    except ImportError:
        return data, _guess_image_mime(data[:32], ext)

    try:
        img = Image.open(io.BytesIO(data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIMENSION:
            scale = MAX_IMAGE_DIMENSION / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception as exc:
        logger.debug("vision.compress_skipped: %s", exc)
        return data, _guess_image_mime(data[:32], ext)


def pdf_bytes_to_images(
    data: bytes,
    *,
    max_pages: int = MAX_VISION_PAGES,
    dpi: int = 200,
) -> List[Tuple[bytes, str]]:
    """Rasterize PDF pages to JPEG bytes for vision models."""
    try:
        import pdf2image
    except ImportError:
        logger.warning("vision.pdf2image_missing")
        return []

    try:
        from PIL import Image

        images = pdf2image.convert_from_bytes(data, dpi=dpi, first_page=1, last_page=max_pages)
    except Exception as exc:
        logger.warning("vision.pdf_convert_failed: %s", exc)
        return []

    out: List[Tuple[bytes, str]] = []
    for image in images:
        buf = io.BytesIO()
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        w, h = image.size
        if max(w, h) > MAX_IMAGE_DIMENSION:
            scale = MAX_IMAGE_DIMENSION / max(w, h)
            image = image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        image.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        out.append((buf.getvalue(), "image/jpeg"))
    return out


def file_bytes_to_vision_images(
    data: bytes,
    file_name: str,
    extension: str,
) -> List[Tuple[bytes, str]]:
    """Normalize upload bytes into JPEG/PNG parts for the vision API."""
    ext = (extension or "").lower().lstrip(".")
    if not ext and file_name:
        parts = file_name.rsplit(".", 1)
        ext = parts[-1].lower() if len(parts) > 1 else ""

    if ext == "pdf" or file_name.lower().endswith(".pdf"):
        pages = pdf_bytes_to_images(data)
        if pages:
            return pages
        return []

    if ext in ALLOWED_IMAGE_EXTENSIONS or ext == "avi":
        compressed, mime = _compress_image_bytes(data, ext)
        return [(compressed, mime)]

    return []


def _parse_bill_date(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    return None


def _normalize_extraction(raw: Dict[str, Any], *, page_count: int = 1) -> Dict[str, Any]:
    """Map LLM JSON to the legacy extracted-bill dict used across the app."""
    conf = raw.get("confidence_score")
    try:
        conf_f = float(conf) if conf is not None else 0.5
    except (TypeError, ValueError):
        conf_f = 0.5
    if conf_f <= 1.0:
        conf_score = round(conf_f * 100.0, 1)
    else:
        conf_score = min(float(conf_f), 100.0)

    bill_date = _parse_bill_date(raw.get("bill_date"))

    def _float(key: str) -> Optional[float]:
        val = raw.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    items = raw.get("items_list") or []
    if not isinstance(items, list):
        items = []

    tax_bd = raw.get("tax_breakdown")
    if tax_bd is not None and not isinstance(tax_bd, dict):
        tax_bd = None

    out: Dict[str, Any] = {
        "vendor_name": (raw.get("vendor_name") or "").strip() or None,
        "restaurant_name": (raw.get("restaurant_name") or "").strip() or None,
        "bill_number": (str(raw.get("bill_number")).strip() if raw.get("bill_number") else None),
        "bill_date": bill_date,
        "total_amount": _float("total_amount"),
        "subtotal": _float("subtotal"),
        "tax_amount": _float("tax_amount"),
        "tax_breakdown": tax_bd,
        "payment_method": (raw.get("payment_method") or "").strip().lower() or None,
        "currency": (raw.get("currency") or "INR").upper(),
        "items_list": items,
        "raw_text": (raw.get("raw_text") or "").strip(),
        "confidence_score": conf_score,
        "ocr_engine_confidence": conf_f if conf_f <= 1.0 else conf_f / 100.0,
        "description": raw.get("description"),
        "main_category_hint": raw.get("main_category_hint"),
        "ocr_provider": "gpt4o_vision",
        "pdf_page_count": page_count if page_count > 1 else raw.get("pdf_page_count"),
    }

    page_extractions = raw.get("page_extractions")
    if isinstance(page_extractions, list) and page_extractions:
        normalized_pages = []
        for i, page in enumerate(page_extractions, start=1):
            if isinstance(page, dict):
                p = _normalize_extraction(page, page_count=1)
                p["page_number"] = i
                normalized_pages.append(p)
        if normalized_pages:
            out["page_extractions"] = normalized_pages

    return out


class VisionReceiptExtractor:
    """OpenAI vision receipt reader — sync and async entry points."""

    def __init__(self) -> None:
        self._model = (
            getattr(settings, "openai_vision_model", None)
            or settings.openai_primary_model
            or settings.openai_model
        )
        self._timeout = float(
            getattr(settings, "openai_vision_timeout_seconds", None)
            or settings.openai_timeout_seconds
            or 90.0
        )
        self._client: Optional[AsyncOpenAI] = None

    def _ensure_client(self) -> AsyncOpenAI:
        key = (settings.openai_api_key or "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not configured — required for receipt scanning")
        if self._client is None:
            self._client = AsyncOpenAI(api_key=key, timeout=self._timeout, max_retries=0)
        return self._client

    def _build_user_parts(
        self,
        images: List[Tuple[bytes, str]],
        *,
        file_name: str,
        page_count: int,
        pdf_text: str = "",
    ) -> List[Dict[str, Any]]:
        intro = (
            f"Extract expense data from this document ({file_name}). "
            f"Pages attached: {len(images)}."
        )
        if page_count > 1:
            intro += " This is a multi-page PDF — include page_extractions when useful."
        parts: List[Dict[str, Any]] = [{"type": "text", "text": intro}]
        if pdf_text.strip():
            parts.append(
                {
                    "type": "text",
                    "text": "--- Embedded PDF text ---\n" + pdf_text.strip(),
                }
            )
        for raw, mime in images:
            b64 = base64.standard_b64encode(raw).decode("ascii")
            parts.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            )
        return parts

    async def _extract_from_text_only(
        self,
        pdf_text: str,
        file_name: str,
    ) -> Dict[str, Any]:
        client = self._ensure_client()
        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Extract expense data from this PDF document ({file_name}). "
                    "No page images are available — use the embedded text below.\n\n"
                    + pdf_text
                ),
            },
        ]
        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = json.loads(response.choices[0].message.content or "{}")
        if not isinstance(raw, dict):
            raw = {}
        return _normalize_extraction(raw, page_count=1)

    async def extract_async(
        self,
        file_data: bytes,
        file_name: str,
        extension: str,
    ) -> Dict[str, Any]:
        ext = (extension or "").lower().lstrip(".")
        pdf_text = _extract_pdf_embedded_text(file_data) if ext == "pdf" else ""
        images = file_bytes_to_vision_images(file_data, file_name, extension)

        if not images and pdf_text.strip():
            return await self._extract_from_text_only(pdf_text, file_name)

        if not images:
            return _normalize_extraction(
                {
                    "raw_text": pdf_text or "",
                    "confidence_score": 0.0,
                    "vendor_name": None,
                    "total_amount": None,
                },
                page_count=0,
            )

        client = self._ensure_client()
        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": self._build_user_parts(
                    images,
                    file_name=file_name,
                    page_count=len(images),
                    pdf_text=pdf_text,
                ),
            },
        ]

        models = [self._model]
        fallback = settings.openai_fallback_model
        if fallback and fallback not in models:
            models.append(fallback)

        last_error: Optional[Exception] = None
        for model in models:
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or "{}"
                raw = json.loads(content)
                if not isinstance(raw, dict):
                    raw = {}
                return _normalize_extraction(raw, page_count=len(images))
            except json.JSONDecodeError:
                logger.warning("vision.invalid_json model=%s file=%s", model, file_name)
                return _normalize_extraction(
                    {"raw_text": "", "confidence_score": 0.2},
                    page_count=len(images),
                )
            except Exception as exc:
                last_error = exc
                logger.warning("vision.extract_failed model=%s file=%s err=%s", model, file_name, exc)
                continue

        raise last_error or RuntimeError(f"Vision extraction failed for {file_name}")

    def extract_sync(
        self,
        file_data: bytes,
        file_name: str,
        extension: str,
    ) -> Dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.extract_async(file_data, file_name, extension))

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                self.extract_async(file_data, file_name, extension),
            )
            return future.result()


def vision_image_parts_for_chat(
    data: bytes,
    file_name: str,
    extension: str,
) -> List[Dict[str, Any]]:
    """OpenAI multimodal parts for chat (no extraction call)."""
    images = file_bytes_to_vision_images(data, file_name, extension)
    parts: List[Dict[str, Any]] = []
    for raw, mime in images:
        b64 = base64.standard_b64encode(raw).decode("ascii")
        parts.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
        )
    return parts
