"""Memory audit history — why preferences changed (PostgreSQL)."""
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.ai.models.entities import AIMemoryAuditEvent
from app.ai.schemas.common import TenantUserContext
from app.ai.security import sanitize_audit_payload


class MemoryAuditService:
    def __init__(self, db: Session):
        self._db = db

    def record(
        self,
        ctx: TenantUserContext,
        *,
        memory_key: str,
        change_type: str,
        source: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        evidence: Optional[Dict[str, Any]] = None,
        confidence_before: Optional[float] = None,
        confidence_after: Optional[float] = None,
    ) -> AIMemoryAuditEvent:
        row = AIMemoryAuditEvent(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            memory_key=memory_key,
            change_type=change_type,
            source=source,
            confidence_before=confidence_before,
            confidence_after=confidence_after,
            before_snapshot=sanitize_audit_payload(before or {}),
            after_snapshot=sanitize_audit_payload(after or {}),
            evidence=sanitize_audit_payload(evidence or {}),
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def list_events(
        self,
        ctx: TenantUserContext,
        *,
        memory_key: Optional[str] = None,
        change_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[AIMemoryAuditEvent], int]:
        q = self._db.query(AIMemoryAuditEvent).filter(
            AIMemoryAuditEvent.tenant_id == ctx.tenant_id,
            AIMemoryAuditEvent.user_id == ctx.user_id,
        )
        if memory_key:
            q = q.filter(AIMemoryAuditEvent.memory_key == memory_key)
        if change_type:
            q = q.filter(AIMemoryAuditEvent.change_type == change_type)
        total = q.count()
        rows = (
            q.order_by(desc(AIMemoryAuditEvent.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return rows, total
