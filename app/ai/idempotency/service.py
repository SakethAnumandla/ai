"""Idempotency for approvals, submissions, reimbursements."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.ai.models.entities import AIIdempotencyRecord
from app.ai.schemas.tool_result import ToolResult
from app.config import settings

logger = logging.getLogger(__name__)


class IdempotencyService:
    def __init__(self, db: Session):
        self._db = db

    def get_existing(
        self,
        *,
        tenant_id: int,
        user_id: int,
        idempotency_key: str,
        action_type: str,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        row = (
            self._db.query(AIIdempotencyRecord)
            .filter(
                AIIdempotencyRecord.tenant_id == tenant_id,
                AIIdempotencyRecord.user_id == user_id,
                AIIdempotencyRecord.idempotency_key == idempotency_key,
                AIIdempotencyRecord.action_type == action_type,
            )
            .first()
        )
        if not row:
            return None
        if row.expires_at and row.expires_at < now:
            return None
        return row.response_payload

    def store(
        self,
        *,
        tenant_id: int,
        user_id: int,
        idempotency_key: str,
        action_type: str,
        result: ToolResult,
    ) -> AIIdempotencyRecord:
        expires = datetime.now(timezone.utc) + timedelta(seconds=settings.ai_idempotency_ttl_seconds)
        existing = (
            self._db.query(AIIdempotencyRecord)
            .filter(
                AIIdempotencyRecord.tenant_id == tenant_id,
                AIIdempotencyRecord.user_id == user_id,
                AIIdempotencyRecord.idempotency_key == idempotency_key,
                AIIdempotencyRecord.action_type == action_type,
            )
            .first()
        )
        payload = result.model_dump()
        if existing:
            existing.response_payload = payload
            existing.status = "completed" if result.success else "failed"
            existing.expires_at = expires
            self._db.commit()
            self._db.refresh(existing)
            return existing

        row = AIIdempotencyRecord(
            tenant_id=tenant_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            action_type=action_type,
            response_payload=payload,
            status="completed" if result.success else "failed",
            expires_at=expires,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        logger.info(
            "idempotency.stored",
            extra={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "action_type": action_type,
            },
        )
        return row
