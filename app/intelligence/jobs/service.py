"""Processing job lifecycle — create, poll, background thread dispatch."""
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.intelligence.schemas import JobStatus, ProcessingJobOut
from app.models import ProcessingJob, ProcessingJobStatus

logger = logging.getLogger(__name__)


def _dispatch_in_background(label: str, fn: Callable[..., None], *args) -> None:
    """Run long jobs off the HTTP thread so POST handlers return 202 quickly."""

    def _runner() -> None:
        try:
            fn(*args)
        except Exception:
            logger.exception("%s background job failed", label)

    threading.Thread(target=_runner, name=f"job-{label}", daemon=True).start()


class JobService:
    def __init__(self, db: Session):
        self._db = db

    def create(
        self,
        *,
        user_id: int,
        tenant_id: int,
        job_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> ProcessingJob:
        row = ProcessingJob(
            user_id=user_id,
            tenant_id=tenant_id,
            job_type=job_type,
            status=ProcessingJobStatus.PENDING.value,
            payload=payload or {},
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def get(self, job_id: int, *, user_id: int) -> Optional[ProcessingJob]:
        return (
            self._db.query(ProcessingJob)
            .filter(ProcessingJob.id == job_id, ProcessingJob.user_id == user_id)
            .first()
        )

    def update_status(
        self,
        job_id: int,
        status: str,
        *,
        progress: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[ProcessingJob]:
        row = self._db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if not row:
            return None
        row.status = status
        if progress is not None:
            row.progress = progress
        if result is not None:
            row.result = result
        if error_message is not None:
            row.error_message = error_message
        if status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value):
            row.completed_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(row)
        return row

    def to_out(self, row: ProcessingJob) -> ProcessingJobOut:
        return ProcessingJobOut(
            id=row.id,
            job_type=row.job_type,
            status=row.status,
            result=row.result,
            error_message=row.error_message,
            created_at=row.created_at,
            completed_at=row.completed_at,
            progress=row.progress,
        )

    def dispatch_receipt_ocr(self, job_id: int, user_id: int) -> None:
        from app.intelligence.tasks.receipt_tasks import run_receipt_ocr_job

        self.update_status(job_id, JobStatus.PENDING.value, progress="queued")
        _dispatch_in_background("receipt-ocr", run_receipt_ocr_job, job_id, user_id)

    def dispatch_voice_transcribe(self, job_id: int, user_id: int) -> None:
        from app.intelligence.tasks.voice_tasks import run_voice_transcribe_job

        self.update_status(job_id, JobStatus.PENDING.value, progress="queued")
        _dispatch_in_background("voice-transcribe", run_voice_transcribe_job, job_id, user_id)

    def dispatch_voice_chat(self, job_id: int, user_id: int) -> None:
        from app.intelligence.tasks.voice_tasks import run_voice_chat_job

        self.update_status(job_id, JobStatus.PENDING.value, progress="queued")
        _dispatch_in_background("voice-chat", run_voice_chat_job, job_id, user_id)

    def dispatch_finance_report(self, job_id: int, user_id: int) -> None:
        from app.finance.tasks.report_tasks import run_finance_report_job

        self.update_status(job_id, JobStatus.PENDING.value, progress="queued")
        _dispatch_in_background("finance-report", run_finance_report_job, job_id, user_id)
