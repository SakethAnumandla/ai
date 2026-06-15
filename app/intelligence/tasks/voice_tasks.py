"""Background jobs for voice transcription and voice→chat pipeline."""
import base64
import logging
import uuid

from app.database import SessionLocal
from app.intelligence.jobs.service import JobService
from app.intelligence.schemas import JobStatus, VoiceChatResult
from app.intelligence.voice.audit import TranscriptionAuditService
from app.intelligence.voice.transcription import TranscriptionService
from app.intelligence.worker_factory import build_orchestrator
from app.ai.security import build_session_context, resolve_tenant_id
from app.config import settings
from app.models import User

logger = logging.getLogger(__name__)


def run_voice_transcribe_job(job_id: int, user_id: int) -> dict:
    db = SessionLocal()
    try:
        jobs = JobService(db)
        jobs.update_status(job_id, JobStatus.PROCESSING.value, progress="transcribing")

        row = jobs.get(job_id, user_id=user_id)
        user = db.query(User).filter(User.id == user_id).first()
        if not row or not user:
            jobs.update_status(job_id, JobStatus.FAILED.value, error_message="not found")
            return {"error": "not found"}

        payload = row.payload or {}
        audio_bytes = base64.b64decode(payload["audio_data_b64"])
        file_name = payload.get("file_name", "audio.webm")
        language = payload.get("language")
        tenant_id = resolve_tenant_id(user)
        audit = TranscriptionAuditService(db)
        transcriber = TranscriptionService()

        try:
            result, latency_ms = transcriber.transcribe_bytes(
                audio_bytes, file_name, language=language
            )
            audit.log(
                user_id=user_id,
                tenant_id=tenant_id,
                job_id=job_id,
                session_id=payload.get("session_id"),
                file_name=file_name,
                file_size=len(audio_bytes),
                language=result.language,
                model=settings.whisper_model,
                transcript=result.transcript,
                duration_seconds=result.duration_seconds,
                latency_ms=latency_ms,
            )
            out = result.model_dump()
            jobs.update_status(job_id, JobStatus.COMPLETED.value, progress="done", result=out)
            return out
        except Exception as exc:
            audit.log(
                user_id=user_id,
                tenant_id=tenant_id,
                job_id=job_id,
                session_id=payload.get("session_id"),
                file_name=file_name,
                file_size=len(audio_bytes),
                language=language,
                model=settings.whisper_model,
                transcript="",
                duration_seconds=None,
                latency_ms=0,
                status="failed",
                error_message=str(exc)[:500],
            )
            raise
    except Exception as exc:
        JobService(db).update_status(
            job_id, JobStatus.FAILED.value, error_message=str(exc)[:2000]
        )
        raise
    finally:
        db.close()


def run_voice_chat_job(job_id: int, user_id: int) -> dict:
    db = SessionLocal()
    try:
        jobs = JobService(db)
        jobs.update_status(job_id, JobStatus.PROCESSING.value, progress="transcribing")

        row = jobs.get(job_id, user_id=user_id)
        user = db.query(User).filter(User.id == user_id).first()
        if not row or not user:
            jobs.update_status(job_id, JobStatus.FAILED.value, error_message="not found")
            return {"error": "not found"}

        payload = row.payload or {}
        transcriber = TranscriptionService()
        audio_bytes = base64.b64decode(payload["audio_data_b64"])
        transcript_result, _ = transcriber.transcribe_bytes(
            audio_bytes,
            payload.get("file_name", "audio.webm"),
            language=payload.get("language"),
        )

        jobs.update_status(job_id, JobStatus.PROCESSING.value, progress="copilot")
        session_id = payload.get("session_id") or str(uuid.uuid4())
        ctx = build_session_context(user, session_id)
        orchestrator = build_orchestrator(db)

        import asyncio

        from app.intelligence.voice.session_flags import VoiceSessionFlags

        async def _voice_chat():
            await VoiceSessionFlags.mark_voice_originated(ctx)
            return await orchestrator.handle_user_message(
                ctx, transcript_result.transcript, user=user
            )

        chat_out = asyncio.run(_voice_chat())

        assistant = chat_out.get("message")
        content = assistant.content if hasattr(assistant, "content") else str(assistant)

        result = VoiceChatResult(
            transcript=transcript_result.transcript,
            language=transcript_result.language,
            session_id=session_id,
            assistant_message=content,
            chat_response={
                k: v for k, v in chat_out.items()
                if k != "message" or not hasattr(v, "model_dump")
            },
        )
        out = result.model_dump(mode="json")
        jobs.update_status(job_id, JobStatus.COMPLETED.value, progress="done", result=out)
        return out
    except Exception as exc:
        logger.exception("voice_chat job %s failed", job_id)
        JobService(db).update_status(
            job_id, JobStatus.FAILED.value, error_message=str(exc)[:2000]
        )
        raise
    finally:
        db.close()
