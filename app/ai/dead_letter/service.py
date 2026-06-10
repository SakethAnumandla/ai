"""Dead letter queue for failed financial / async AI tool jobs."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.models.entities import AIJobDeadLetter

logger = logging.getLogger(__name__)

_FINANCIAL_JOB_TYPES = frozenset({
    "expense.submit.v1",
    "approval.submit.v1",
    "reimbursement.submit.v1",
    "expense.submit",
    "approval.submit",
    "reimbursement.submit",
})


class DeadLetterQueueService:
    def __init__(self, db: Session):
        self._db = db

    def enqueue(
        self,
        *,
        tenant_id: int,
        user_id: int,
        session_id: Optional[str],
        job_type: str,
        payload: Dict[str, Any],
        error_message: str,
        trace_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> AIJobDeadLetter:
        row = AIJobDeadLetter(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            job_type=job_type,
            payload=payload,
            error_message=error_message[:2000],
            status="failed",
            retry_count=0,
            trace_id=trace_id,
            request_id=request_id,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        logger.error(
            "dlq.enqueued",
            extra={"job_type": job_type, "tenant_id": tenant_id, "dlq_id": row.id},
        )
        return row

    def should_enqueue(self, job_type: str) -> bool:
        return job_type in _FINANCIAL_JOB_TYPES or any(
            x in job_type for x in ("submit", "approval", "reimbursement")
        )

    def list_failed(
        self,
        *,
        tenant_id: int,
        user_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[AIJobDeadLetter]:
        q = self._db.query(AIJobDeadLetter).filter(
            AIJobDeadLetter.tenant_id == tenant_id,
            AIJobDeadLetter.status.in_(("failed", "retry_pending")),
        )
        if user_id is not None:
            q = q.filter(AIJobDeadLetter.user_id == user_id)
        return q.order_by(AIJobDeadLetter.created_at.desc()).limit(limit).all()

    def mark_retry_pending(self, dlq_id: int, *, tenant_id: int) -> Optional[AIJobDeadLetter]:
        row = (
            self._db.query(AIJobDeadLetter)
            .filter(AIJobDeadLetter.id == dlq_id, AIJobDeadLetter.tenant_id == tenant_id)
            .first()
        )
        if not row:
            return None
        row.status = "retry_pending"
        row.retry_count = (row.retry_count or 0) + 1
        row.last_retry_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(row)
        return row

    def mark_resolved(self, dlq_id: int, *, tenant_id: int) -> None:
        row = (
            self._db.query(AIJobDeadLetter)
            .filter(AIJobDeadLetter.id == dlq_id, AIJobDeadLetter.tenant_id == tenant_id)
            .first()
        )
        if row:
            row.status = "resolved"
            row.resolved_at = datetime.now(timezone.utc)
            self._db.commit()
