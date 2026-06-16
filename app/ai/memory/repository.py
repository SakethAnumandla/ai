"""Repository pattern for AI PostgreSQL persistence."""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.ai.models.entities import (
    AIAction,
    AIConversation,
    AIMemory,
    AIMemoryAuditEvent,
    AISummary,
)
from app.ai.schemas.audit import AuditLogCreate
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.schemas.conversation import ConversationMessageCreate
from app.ai.schemas.memory import MemoryEntryCreate
from app.ai.sanitization import sanitize_prompt, sanitize_response
from app.ai.security import sanitize_audit_payload


class AIRepository:
    """Data access for AI tables with mandatory tenant/user scoping."""

    def __init__(self, db: Session):
        self.db = db

    def save_conversation_message(
        self,
        ctx: SessionContext,
        message: ConversationMessageCreate,
    ) -> AIConversation:
        if message.role.value == "user":
            safe_content = sanitize_prompt(message.content)
        else:
            safe_content = sanitize_response(message.content)

        row = AIConversation(
            tenant_id=ctx.scoped_company_id,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            role=message.role.value,
            content=safe_content if isinstance(safe_content, str) else message.content,
            metadata_=message.metadata,
            token_count=message.token_count,
        )
        self.db.add(row)
        self._touch_chat_session(ctx, message)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _touch_chat_session(self, ctx: SessionContext, message: ConversationMessageCreate) -> None:
        from app.models import AIChatSession

        title = None
        if message.role.value == "user":
            title = (message.content or "")[:120].strip() or None
        existing = (
            self.db.query(AIChatSession)
            .filter(
                AIChatSession.tenant_id == ctx.scoped_company_id,
                AIChatSession.user_id == ctx.user_id,
                AIChatSession.session_id == ctx.session_id,
            )
            .first()
        )
        if existing:
            existing.message_count = (existing.message_count or 0) + 1
            if title and (not existing.title or existing.title == "Expense chat"):
                existing.title = title
            existing.is_active = True
        else:
            self.db.add(
                AIChatSession(
                    tenant_id=ctx.scoped_company_id,
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    title=title or "Expense chat",
                    message_count=1,
                    is_active=True,
                )
            )

    def fetch_recent_messages(
        self,
        ctx: SessionContext,
        *,
        limit: int = 20,
    ) -> List[AIConversation]:
        return (
            self.db.query(AIConversation)
            .filter(
                AIConversation.tenant_id == ctx.scoped_company_id,
                AIConversation.user_id == ctx.user_id,
                AIConversation.session_id == ctx.session_id,
            )
            .order_by(desc(AIConversation.created_at))
            .limit(limit)
            .all()
        )[::-1]

    def save_memory(
        self,
        ctx: TenantUserContext,
        entry: MemoryEntryCreate,
    ) -> AIMemory:
        existing = (
            self.db.query(AIMemory)
            .filter(
                AIMemory.tenant_id == ctx.tenant_id,
                AIMemory.user_id == ctx.user_id,
                AIMemory.memory_key == entry.memory_key,
            )
            .first()
        )
        if existing:
            existing.memory_type = entry.memory_type.value
            existing.value = entry.value
            existing.importance = entry.importance
            existing.expires_at = entry.expires_at
            existing.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(existing)
            return existing

        row = AIMemory(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            memory_type=entry.memory_type.value,
            memory_key=entry.memory_key,
            value=entry.value,
            importance=entry.importance,
            expires_at=entry.expires_at,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update_importance(self, memory_id: int, importance: float) -> None:
        row = self.db.query(AIMemory).filter(AIMemory.id == memory_id).first()
        if row:
            row.importance = importance
            row.updated_at = datetime.now(timezone.utc)
            self.db.commit()

    def purge_expired_memories(self, ctx: TenantUserContext) -> int:
        now = datetime.now(timezone.utc)
        q = self.db.query(AIMemory).filter(
            AIMemory.tenant_id == ctx.tenant_id,
            AIMemory.user_id == ctx.user_id,
            AIMemory.expires_at.isnot(None),
            AIMemory.expires_at <= now,
        )
        count = q.count()
        q.delete(synchronize_session=False)
        self.db.commit()
        return count

    def fetch_memories_by_type(
        self,
        ctx: TenantUserContext,
        memory_type: str,
        *,
        limit: int = 30,
    ) -> List[AIMemory]:
        now = datetime.now(timezone.utc)
        return (
            self.db.query(AIMemory)
            .filter(
                AIMemory.tenant_id == ctx.tenant_id,
                AIMemory.user_id == ctx.user_id,
                AIMemory.memory_type == memory_type,
            )
            .filter((AIMemory.expires_at.is_(None)) | (AIMemory.expires_at > now))
            .order_by(desc(AIMemory.importance), desc(AIMemory.updated_at))
            .limit(limit)
            .all()
        )

    def fetch_memories(
        self,
        ctx: TenantUserContext,
        *,
        limit: int = 50,
    ) -> List[AIMemory]:
        now = datetime.now(timezone.utc)
        q = self.db.query(AIMemory).filter(
            AIMemory.tenant_id == ctx.tenant_id,
            AIMemory.user_id == ctx.user_id,
        )
        q = q.filter(
            (AIMemory.expires_at.is_(None)) | (AIMemory.expires_at > now)
        )
        return q.order_by(desc(AIMemory.importance), desc(AIMemory.updated_at)).limit(limit).all()

    def save_summary(
        self,
        ctx: SessionContext,
        *,
        summary_text: str,
        token_count_before: int,
        token_count_after: int,
        model: Optional[str],
    ) -> AISummary:
        safe_summary = sanitize_response(summary_text)
        if not isinstance(safe_summary, str):
            safe_summary = summary_text

        row = AISummary(
            tenant_id=ctx.scoped_company_id,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            summary_text=safe_summary,
            token_count_before=token_count_before,
            token_count_after=token_count_after,
            model=model,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def fetch_memory_by_key(
        self,
        ctx: TenantUserContext,
        memory_key: str,
    ) -> Optional[AIMemory]:
        now = datetime.now(timezone.utc)
        return (
            self.db.query(AIMemory)
            .filter(
                AIMemory.tenant_id == ctx.tenant_id,
                AIMemory.user_id == ctx.user_id,
                AIMemory.memory_key == memory_key,
            )
            .filter((AIMemory.expires_at.is_(None)) | (AIMemory.expires_at > now))
            .first()
        )

    def delete_memory_by_key(
        self,
        ctx: TenantUserContext,
        memory_key: str,
    ) -> int:
        q = self.db.query(AIMemory).filter(
            AIMemory.tenant_id == ctx.tenant_id,
            AIMemory.user_id == ctx.user_id,
            AIMemory.memory_key == memory_key,
        )
        count = q.count()
        q.delete(synchronize_session=False)
        self.db.commit()
        return count

    def delete_session_scoped_memories(self, ctx: SessionContext) -> int:
        """Delete draft/intent/workflow rows stored under this session_id."""
        company_id = ctx.scoped_company_id
        suffix = f":{ctx.session_id}"
        q = self.db.query(AIMemory).filter(
            AIMemory.tenant_id == company_id,
            AIMemory.user_id == ctx.user_id,
            AIMemory.memory_key.like(f"%{suffix}"),
        )
        count = q.count()
        q.delete(synchronize_session=False)
        self.db.commit()
        return count

    def fetch_latest_summary(self, ctx: SessionContext) -> Optional[AISummary]:
        return (
            self.db.query(AISummary)
            .filter(
                AISummary.tenant_id == ctx.scoped_company_id,
                AISummary.user_id == ctx.user_id,
                AISummary.session_id == ctx.session_id,
            )
            .order_by(desc(AISummary.created_at))
            .first()
        )

    def log_action(
        self,
        ctx: TenantUserContext,
        audit: AuditLogCreate,
    ) -> AIAction:
        usage = audit.token_usage
        row = AIAction(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            session_id=audit.session_id,
            request_id=audit.request_id,
            trace_id=audit.trace_id,
            action_type=audit.action_type.value,
            tool_name=audit.tool_name,
            model=audit.model,
            payload=sanitize_audit_payload(audit.payload),
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            latency_ms=audit.latency_ms,
            status=audit.status,
            error_message=audit.error_message,
            parent_audit_id=audit.parent_audit_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_active_model_config(self, tenant_id: int):
        from app.ai.models.entities import AIModelConfig

        return (
            self.db.query(AIModelConfig)
            .filter(AIModelConfig.tenant_id == tenant_id, AIModelConfig.active.is_(True))
            .order_by(AIModelConfig.updated_at.desc())
            .first()
        )
