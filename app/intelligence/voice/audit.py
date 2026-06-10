"""Transcription audit logging."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import VoiceTranscriptionAudit


class TranscriptionAuditService:
    def __init__(self, db: Session):
        self._db = db

    def log(
        self,
        *,
        user_id: int,
        tenant_id: int,
        job_id: Optional[int],
        session_id: Optional[str],
        file_name: Optional[str],
        file_size: Optional[int],
        language: Optional[str],
        model: str,
        transcript: str,
        duration_seconds: Optional[float],
        latency_ms: int,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> VoiceTranscriptionAudit:
        preview = transcript[:500] if transcript else ""
        row = VoiceTranscriptionAudit(
            user_id=user_id,
            tenant_id=tenant_id,
            job_id=job_id,
            session_id=session_id,
            file_name=file_name,
            file_size=file_size,
            language=language,
            model=model,
            transcript_preview=preview,
            duration_seconds=duration_seconds,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row
