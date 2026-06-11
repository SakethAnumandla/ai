"""Whisper transcription service (OpenAI API)."""
import logging
import os
import tempfile
import time
from typing import Optional, Tuple

from openai import OpenAI

from app.config import settings
from app.intelligence.schemas import VoiceTranscriptionResult

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Async-capable wrapper around OpenAI Whisper."""

    def __init__(self, *, model: Optional[str] = None):
        self._model = model or settings.whisper_model
        self._client: Optional[OpenAI] = None

    def _ensure_client(self) -> OpenAI:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if self._client is None:
            self._client = OpenAI(api_key=settings.openai_api_key)
        return self._client

    def transcribe_bytes(
        self,
        audio_data: bytes,
        file_name: str,
        *,
        language: Optional[str] = None,
    ) -> Tuple[VoiceTranscriptionResult, int]:
        """
        Transcribe audio bytes. Returns (result, latency_ms).
        language: ISO-639-1 hint (e.g. 'en', 'hi'); None = auto-detect.
        """
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "webm"
        if ext not in settings.voice_allowed_extensions:
            ext = "webm"

        start = time.perf_counter()
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            client = self._ensure_client()
            with open(tmp_path, "rb") as audio_file:
                kwargs = {"model": self._model, "file": audio_file}
                if language:
                    kwargs["language"] = language
                response = client.audio.transcriptions.create(**kwargs)

            latency_ms = int((time.perf_counter() - start) * 1000)
            text = (response.text or "").strip()
            detected_lang = getattr(response, "language", None) or language

            return (
                VoiceTranscriptionResult(
                    transcript=text,
                    language=detected_lang,
                    confidence=0.85 if text else 0.0,
                ),
                latency_ms,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
