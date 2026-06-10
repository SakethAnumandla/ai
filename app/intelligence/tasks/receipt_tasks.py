"""Celery tasks for receipt OCR intelligence."""
import asyncio
import base64
import logging

from app.database import SessionLocal
from app.ai.memory.repository import AIRepository
from app.ai.memory.redis_store import RedisMemoryStore
from app.ai.memory.resilient_store import ResilientMemoryStore
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.security import resolve_tenant_id
from app.ai.services.audit_service import AuditService
from app.ai.services.memory_service import MemoryService
from app.ai.services.openai_service import OpenAIService
from app.intelligence.jobs.service import JobService
from app.intelligence.receipt.pipeline import ReceiptIntelligencePipeline
from app.intelligence.schemas import JobStatus
from app.intelligence.tasks.celery_app import celery_app
from app.models import User

logger = logging.getLogger(__name__)


async def _persist_draft_memory(db, user: User, pipeline: ReceiptIntelligencePipeline, result) -> None:
    redis = RedisMemoryStore()
    try:
        await redis.connect()
    except Exception:
        pass
    repo = AIRepository(db)
    store = ResilientMemoryStore(redis, repo)
    await store.connect()
    memory = MemoryService(repo, store, OpenAIService(), AuditService(repo))
    tu = TenantUserContext(tenant_id=resolve_tenant_id(user), user_id=user.id)
    draft_ctx = pipeline.build_draft_context(result)
    session_id = f"receipt-{draft_ctx.expense_id or 'scan'}"
    mem_ctx = SessionContext(
        tenant_id=tu.tenant_id, user_id=tu.user_id, session_id=session_id
    )
    await memory.set_draft_expense(mem_ctx, draft_ctx)


def run_receipt_ocr_job(job_id: int, user_id: int) -> dict:
    db = SessionLocal()
    try:
        jobs = JobService(db)
        jobs.update_status(job_id, JobStatus.PROCESSING.value, progress="ocr_running")

        row = jobs.get(job_id, user_id=user_id)
        if not row:
            return {"error": "job not found"}

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            jobs.update_status(job_id, JobStatus.FAILED.value, error_message="user not found")
            return {"error": "user not found"}

        payload = row.payload or {}
        file_data_b64 = payload.get("file_data_b64")
        if not file_data_b64:
            jobs.update_status(job_id, JobStatus.FAILED.value, error_message="missing file data")
            return {"error": "missing file"}

        file_info = {
            "file_data": base64.b64decode(file_data_b64),
            "file_name": payload.get("file_name", "receipt.jpg"),
            "file_extension": payload.get("file_extension", "jpg"),
            "file_hash": payload.get("file_hash"),
            "mime_type": payload.get("mime_type"),
            "file_size": payload.get("file_size"),
        }

        pipeline = ReceiptIntelligencePipeline(db)
        result = pipeline.run_sync(
            user,
            file_info,
            bill_index=payload.get("bill_index", 0),
            force_rescan=payload.get("force_rescan", False),
        )

        try:
            asyncio.run(_persist_draft_memory(db, user, pipeline, result))
        except Exception as mem_exc:
            logger.warning("draft memory save failed: %s", mem_exc)

        out = result.model_dump(mode="json")
        jobs.update_status(job_id, JobStatus.COMPLETED.value, progress="done", result=out)
        return out
    except Exception as exc:
        logger.exception("receipt_ocr job %s failed", job_id)
        JobService(db).update_status(
            job_id, JobStatus.FAILED.value, error_message=str(exc)[:2000]
        )
        raise
    finally:
        db.close()


@celery_app.task(name="intelligence.process_receipt_ocr", bind=True, max_retries=2)
def process_receipt_ocr_task(self, job_id: int, user_id: int):
    return run_receipt_ocr_job(job_id, user_id)
