"""Build OpenAI-ready multimodal content from chat uploads (images + PDF)."""
import base64
import io
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from fastapi import HTTPException, UploadFile, status

logger = logging.getLogger(__name__)

LlmUserContent = Union[str, List[Dict[str, Any]]]

ALLOWED_IMAGE_MIMES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)
PDF_MIME = "application/pdf"
MAX_FILES = 5
PDF_MAX_PAGES = 12
PDF_MAX_CHARS = 14000


def _guess_image_mime(head: bytes, declared: Optional[str]) -> Optional[str]:
    if len(head) >= 3 and head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(head) >= 8 and head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(head) >= 6 and head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if declared and declared.split(";")[0].strip().lower() in ALLOWED_IMAGE_MIMES:
        return declared.split(";")[0].strip().lower()
    return None


def _extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "[PDF parsing unavailable]"

    try:
        reader = PdfReader(io.BytesIO(data))
        chunks: List[str] = []
        for _, page in enumerate(reader.pages[:PDF_MAX_PAGES]):
            t = page.extract_text() or ""
            if t.strip():
                chunks.append(t.strip())
        full = "\n\n".join(chunks).strip()
        if not full:
            return (
                "(No selectable text found in this PDF. It may be a scanned image — "
                "ask the user to attach a photo or use the OCR bill scan endpoint.)"
            )
        if len(full) > PDF_MAX_CHARS:
            return full[:PDF_MAX_CHARS] + "\n…[truncated]"
        return full
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdf.extract_failed: %s", exc)
        return f"(Could not read PDF: {exc})"


@dataclass
class ChatAttachmentResult:
    """What to persist vs what to send to the vision model."""

    intent_message: str
    persist_message: str
    llm_user_content: LlmUserContent


def _build_bundle_from_bytes(
    *,
    message: str,
    items: List[tuple[str, bytes, Optional[str]]],
) -> ChatAttachmentResult:
    """items: (filename, raw bytes, optional content-type)."""
    cleaned = (message or "").strip()
    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No readable files were uploaded",
        )

    image_parts: List[tuple[str, str]] = []
    pdf_summaries: List[str] = []
    names: List[str] = []

    for filename, raw, content_type in items:
        names.append(filename)
        ctype = (content_type or "").split(";")[0].strip().lower()

        if ctype == PDF_MIME or filename.lower().endswith(".pdf"):
            text = _extract_pdf_text(raw)
            pdf_summaries.append(f"--- {filename} ---\n{text}")
            continue

        mime_guess = _guess_image_mime(raw[:32], content_type)
        if not mime_guess:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type for {filename}. "
                "Use JPEG, PNG, WebP, GIF, or PDF.",
            )
        b64 = base64.standard_b64encode(raw).decode("ascii")
        image_parts.append((mime_guess, b64))

    attach_note = " ".join(f"[Attached: {n}]" for n in names)
    base_text = cleaned if cleaned else (
        "I've attached expense document(s). Please read them and help me record or review the expense."
    )
    persist_message = f"{base_text}\n{attach_note}".strip()

    parts: List[Dict[str, Any]] = [{"type": "text", "text": base_text}]
    if pdf_summaries:
        parts.append(
            {
                "type": "text",
                "text": "--- Extracted PDF text (may be partial) ---\n"
                + "\n\n".join(pdf_summaries),
            }
        )
    for mime, b64 in image_parts:
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )

    return ChatAttachmentResult(
        intent_message=base_text,
        persist_message=persist_message,
        llm_user_content=parts,
    )


def build_chat_attachment_bundle_from_file_infos(
    *,
    message: str,
    file_infos: List[dict],
    max_bytes_per_file: int,
) -> ChatAttachmentResult:
    """Vision/PDF-text path using already-read upload bytes (e.g. GIF after OCR receipts)."""
    if len(file_infos) > MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most {MAX_FILES} files allowed per message",
        )
    items: List[tuple[str, bytes, Optional[str]]] = []
    for fi in file_infos:
        raw = fi.get("file_data") or b""
        if len(raw) > max_bytes_per_file:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File {fi.get('file_name')} exceeds maximum size ({max_bytes_per_file} bytes)",
            )
        items.append(
            (
                fi.get("file_name") or "attachment",
                raw,
                fi.get("mime_type"),
            )
        )
    return _build_bundle_from_bytes(message=message, items=items)


async def build_chat_attachment_bundle(
    *,
    message: str,
    files: List[UploadFile],
    max_bytes_per_file: int,
) -> ChatAttachmentResult:
    """
    Validate uploads and produce persistence line + multimodal OpenAI user content.

    `message` may be empty when files are present (caller should pass intent default separately).
    """
    cleaned = (message or "").strip()
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file is required for this endpoint",
        )

    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"At most {MAX_FILES} files allowed per message",
        )

    items: List[tuple[str, bytes, Optional[str]]] = []
    for upload in files:
        if not upload or not upload.filename:
            continue
        raw = await upload.read()
        if len(raw) > max_bytes_per_file:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File {upload.filename} exceeds maximum size ({max_bytes_per_file} bytes)",
            )
        items.append((upload.filename, raw, upload.content_type))

    return _build_bundle_from_bytes(message=message, items=items)
