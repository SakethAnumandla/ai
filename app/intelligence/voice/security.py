"""Audio upload validation — size, mime, duration, basic malware patterns."""
import struct
from dataclasses import dataclass
from typing import Optional, Set, Tuple

from fastapi import HTTPException, status

from app.config import settings

# Magic byte signatures for allowed audio containers
_AUDIO_SIGNATURES: dict[str, list[bytes]] = {
    "webm": [b"\x1a\x45\xdf\xa3"],
    "ogg": [b"OggS"],
    "wav": [b"RIFF"],
    "mp3": [b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"],
    "m4a": [b"\x00\x00\x00"],
    "mp4": [b"\x00\x00\x00"],
}

_BLOCKED_PATTERNS = (
    b"<?php",
    b"<script",
    b"MZ",
    b"\x7fELF",
)


@dataclass
class AudioValidationResult:
    ok: bool
    extension: str
    mime_type: str
    size_bytes: int
    estimated_duration_seconds: Optional[float] = None
    error: Optional[str] = None


class AudioUploadValidator:
    def __init__(self):
        self._max_bytes = settings.voice_max_audio_bytes
        self._max_duration = settings.voice_max_duration_seconds
        self._allowed_ext: Set[str] = set(settings.voice_allowed_extensions)
        self._allowed_mime: Set[str] = set(settings.voice_allowed_mime_types)

    def validate(
        self,
        data: bytes,
        file_name: str,
        content_type: Optional[str] = None,
    ) -> AudioValidationResult:
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty audio file",
            )

        if len(data) > self._max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Audio exceeds maximum size ({self._max_bytes // (1024*1024)} MB)",
            )

        for pattern in _BLOCKED_PATTERNS:
            if pattern in data[:4096]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File content not allowed",
                )

        ext = (file_name or "audio.webm").rsplit(".", 1)[-1].lower()
        if ext not in self._allowed_ext:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported audio extension. Allowed: {sorted(self._allowed_ext)}",
            )

        mime = (content_type or "").split(";")[0].strip().lower()
        if mime and mime not in self._allowed_mime and not mime.startswith("audio/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported MIME type: {mime}",
            )

        if not self._check_magic(data, ext):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File content does not match declared audio format",
            )

        duration = self._estimate_duration(data, ext)
        if duration is not None and duration > self._max_duration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Audio exceeds maximum duration ({self._max_duration}s)",
            )

        return AudioValidationResult(
            ok=True,
            extension=ext,
            mime_type=mime or f"audio/{ext}",
            size_bytes=len(data),
            estimated_duration_seconds=duration,
        )

    def _check_magic(self, data: bytes, ext: str) -> bool:
        sigs = _AUDIO_SIGNATURES.get(ext, [])
        if not sigs:
            return len(data) >= 4
        header = data[:12]
        return any(header.startswith(s) for s in sigs)

    def _estimate_duration(self, data: bytes, ext: str) -> Optional[float]:
        if ext == "wav" and len(data) > 44:
            try:
                if data[:4] == b"RIFF":
                    _, _, _, fmt_size = struct.unpack("<4sI4sI", data[:16])
                    if fmt_size >= 16:
                        audio_format, channels, sample_rate, byte_rate = struct.unpack(
                            "<HHII", data[20:32]
                        )
                        if byte_rate > 0:
                            return (len(data) - 44) / byte_rate
            except struct.error:
                pass
        # Conservative estimate for compressed formats (~128kbps)
        return len(data) / (16 * 1024)
