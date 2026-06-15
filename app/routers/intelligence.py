"""Phase 4 — Voice + Receipt Intelligence APIs."""
import base64
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.database import get_db
from app.dependencies import get_current_user
from app.intelligence.jobs.service import JobService
from app.intelligence.schemas import (
    JobType,
    ProcessingJobOut,
    ReceiptReviewConfirmRequest,
    VoiceTranscriptionResult,
)
from app.intelligence.voice.security import AudioUploadValidator
from app.models import User
from app.utils.file_upload import process_single_file

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

RECEIPT_EXTENSIONS = {"jpg", "jpeg", "png", "pdf", "webp"}
_audio_validator = AudioUploadValidator()


def _job_out(db: Session, job_id: int, user_id: int) -> ProcessingJobOut:
    row = JobService(db).get(job_id, user_id=user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobService(db).to_out(row)


async def _read_validated_audio(file: UploadFile) -> bytes:
    data = await file.read()
    _audio_validator.validate(
        data,
        file.filename or "audio.webm",
        content_type=file.content_type,
    )
    return data


@router.get("/jobs/{job_id}", response_model=ProcessingJobOut)
def get_job_status(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Poll async voice, receipt, or finance report job status."""
    return _job_out(db, job_id, user.id)


# --- Voice ---


@router.post("/voice/transcribe", response_model=ProcessingJobOut, status_code=status.HTTP_202_ACCEPTED)
async def voice_transcribe_async(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None, description="ISO-639-1 hint, e.g. en, hi"),
    session_id: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload audio from Flutter mic → Whisper transcription (async).
    Poll GET /intelligence/jobs/{id} for result.
    """
    data = await _read_validated_audio(file)

    tenant_id = resolve_tenant_id(user)
    jobs = JobService(db)
    job = jobs.create(
        user_id=user.id,
        tenant_id=tenant_id,
        job_type=JobType.VOICE_TRANSCRIBE.value,
        payload={
            "audio_data_b64": base64.b64encode(data).decode("ascii"),
            "file_name": file.filename,
            "language": language,
            "session_id": session_id,
        },
    )
    jobs.dispatch_voice_transcribe(job.id, user.id)
    return jobs.to_out(job)


@router.post("/voice/transcribe-sync", response_model=VoiceTranscriptionResult)
async def voice_transcribe_sync(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None, description="ISO-639-1 hint, e.g. en, hi"),
    session_id: Optional[str] = Form(
        None, description="AI chat session_id (8–64 chars) for voice-aware replies"
    ),
    user: User = Depends(get_current_user),
):
    """Synchronous Whisper transcription for push-to-talk in the expense copilot."""
    from app.ai.security import build_session_context
    from app.intelligence.voice.session_flags import VoiceSessionFlags
    from app.intelligence.voice.transcription import TranscriptionService

    data = await _read_validated_audio(file)
    transcriber = TranscriptionService()
    try:
        result, _ = transcriber.transcribe_bytes(
            data,
            file.filename or "audio.webm",
            language=language,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc) or "Voice transcription is not configured",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not transcribe audio. Try a clearer recording.",
        ) from exc

    sid = (session_id or "").strip()
    if len(sid) >= 8:
        ctx = build_session_context(user, sid)
        await VoiceSessionFlags.mark_voice_originated(ctx)

    if not (result.transcript or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="I couldn't hear anything clear. Try again closer to the microphone.",
        )

    return result


@router.post("/voice/chat", response_model=ProcessingJobOut, status_code=status.HTTP_202_ACCEPTED)
async def voice_chat_async(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Flutter mic → Whisper → AI orchestrator → conversational response (async).
    Voice sessions enforce stricter confirmation for financial tools.
    """
    data = await _read_validated_audio(file)

    tenant_id = resolve_tenant_id(user)
    jobs = JobService(db)
    job = jobs.create(
        user_id=user.id,
        tenant_id=tenant_id,
        job_type=JobType.VOICE_CHAT.value,
        payload={
            "audio_data_b64": base64.b64encode(data).decode("ascii"),
            "file_name": file.filename,
            "language": language,
            "session_id": session_id,
        },
    )
    jobs.dispatch_voice_chat(job.id, user.id)
    return jobs.to_out(job)


# --- Receipt ---


@router.post("/receipt/scan", response_model=ProcessingJobOut, status_code=status.HTTP_202_ACCEPTED)
async def receipt_scan_async(
    file: UploadFile = File(...),
    force_rescan: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Image/PDF upload → LLM vision scan → entity extraction → fraud checks → autofill → draft (async).
    Poll GET /intelligence/jobs/{id} for ReceiptPipelineResult.
    """
    ext = (file.filename or "receipt.jpg").rsplit(".", 1)[-1].lower()
    if ext not in RECEIPT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {sorted(RECEIPT_EXTENSIONS)}",
        )

    file_info = await process_single_file(file)
    if not file_info.get("file_data"):
        raise HTTPException(status_code=400, detail="Empty file upload")

    tenant_id = resolve_tenant_id(user)
    jobs = JobService(db)
    job = jobs.create(
        user_id=user.id,
        tenant_id=tenant_id,
        job_type=JobType.RECEIPT_OCR.value,
        payload={
            "file_data_b64": base64.b64encode(file_info["file_data"]).decode("ascii"),
            "file_name": file_info["file_name"],
            "file_extension": file_info.get("file_extension", ext),
            "file_hash": file_info.get("file_hash"),
            "mime_type": file_info.get("mime_type"),
            "file_size": file_info.get("file_size"),
            "force_rescan": force_rescan,
        },
    )
    jobs.dispatch_receipt_ocr(job.id, user.id)
    return jobs.to_out(job)


@router.post("/receipt/scan-sync")
async def receipt_scan_sync(
    file: UploadFile = File(...),
    force_rescan: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Synchronous receipt scan for local dev (blocks until complete)."""
    from app.intelligence.receipt.pipeline import ReceiptIntelligencePipeline
    from app.ai.memory.repository import AIRepository
    from app.ai.memory.resilient_store import ResilientMemoryStore
    from app.ai.services.memory_service import MemoryService
    from app.ai.services.openai_service import OpenAIService
    from app.ai.services.audit_service import AuditService
    from app.ai.schemas.common import SessionContext, TenantUserContext

    file_info = await process_single_file(file)
    if not file_info.get("file_data"):
        raise HTTPException(status_code=400, detail="Empty file upload")

    pipeline = ReceiptIntelligencePipeline(db)
    try:
        from app.utils.async_io import run_blocking

        result = await run_blocking(
            pipeline.run_sync,
            user,
            file_info,
            force_rescan=force_rescan,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc) or "Could not process receipt image",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not process receipt. Use a clear photo in good lighting.",
        ) from exc

    try:
        repo = AIRepository(db)
        store = ResilientMemoryStore(repo)
        await store.connect()
        memory = MemoryService(repo, store, OpenAIService(), AuditService(repo))
        tu = TenantUserContext(tenant_id=resolve_tenant_id(user), user_id=user.id)
        draft_ctx = pipeline.build_draft_context(result)
        session_id = f"receipt-{draft_ctx.expense_id or 'scan'}"
        mem_ctx = SessionContext(
            tenant_id=tu.tenant_id, user_id=tu.user_id, session_id=session_id
        )
        await memory.set_draft_expense(mem_ctx, draft_ctx)
    except Exception:
        pass

    return result.model_dump(mode="json")


@router.post("/receipt/{expense_id}/confirm-review")
async def receipt_confirm_review(
    expense_id: int,
    body: ReceiptReviewConfirmRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Confirm human-reviewed OCR fields after low-confidence or fraud-flagged scan.
    """
    from app.intelligence.receipt.human_review import HumanReviewService

    service = HumanReviewService(db)
    try:
        expense = service.confirm_review(
            user_id=user.id,
            expense_id=expense_id,
            review_token=body.review_token,
            corrections=body.corrections,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "expense_id": expense.id,
        "status": expense.status.value if hasattr(expense.status, "value") else str(expense.status),
        "review_status": "confirmed",
        "bill_amount": expense.bill_amount,
        "vendor_name": expense.vendor_name,
        "bill_name": expense.bill_name,
    }
