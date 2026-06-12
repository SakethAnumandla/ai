"""Session state in PostgreSQL (via AIRepository); optional Redis cache when available."""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.ai.json_util import draft_context_to_storage
from app.ai.memory.redis_store import RedisMemoryStore
from app.ai.memory.repository import AIRepository
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.models.entities import MemoryType
from app.ai.schemas.memory import DraftExpenseContext, MemoryEntryCreate, PendingIntent
from app.ai.schemas.workflow import ConversationWorkflowState

logger = logging.getLogger(__name__)

_DRAFT_KEY = "session:draft_expense"
_DRAFTS_LIST_KEY = "session:draft_expenses_list"
_INTENT_KEY = "session:pending_intent"
_WORKFLOW_KEY = "workflow:state"


def _scoped_key(base: str, ctx: SessionContext) -> str:
    return f"{base}:{ctx.session_id}"


class ResilientMemoryStore:
    """
    Persists draft expenses, pending intents, and workflow state in PostgreSQL (ai_memory).
    Uses Redis only as an optional cache when connected.
    """

    def __init__(self, redis: RedisMemoryStore, repository: AIRepository):
        self._redis = redis
        self._repo = repository
        self._redis_available = False

    @property
    def redis_available(self) -> bool:
        return self._redis_available and self._redis.is_connected

    async def connect(self) -> None:
        try:
            await self._redis.connect()
            self._redis_available = True
        except Exception as exc:
            self._redis_available = False
            logger.warning("Redis unavailable, using Postgres only for session state: %s", exc)

    async def disconnect(self) -> None:
        await self._redis.disconnect()

    async def append_session_message(
        self,
        ctx: SessionContext,
        message: Dict[str, Any],
        *,
        ttl: Optional[int] = None,
    ) -> None:
        if not self.redis_available:
            return
        try:
            await self._redis.append_session_message(ctx, message, ttl=ttl)
        except Exception as exc:
            logger.warning("Redis session cache append failed: %s", exc)

    async def get_session_messages(
        self,
        ctx: SessionContext,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        if self.redis_available:
            try:
                return await self._redis.get_session_messages(ctx, limit=limit)
            except Exception as exc:
                logger.warning("Redis session cache read failed: %s", exc)

        rows = await asyncio.to_thread(self._repo.fetch_recent_messages, ctx, limit=limit)
        return [
            {
                "role": r.role,
                "content": r.content,
                "token_count": r.token_count or 0,
            }
            for r in rows
        ]

    async def set_draft_expense(
        self,
        ctx: SessionContext,
        draft: DraftExpenseContext,
        *,
        ttl: Optional[int] = None,
    ) -> None:
        if self.redis_available:
            try:
                await self._redis.set_draft_expense(ctx, draft, ttl=ttl)
            except Exception as exc:
                logger.warning("Redis draft cache failed: %s", exc)

        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        await asyncio.to_thread(
            self._repo.save_memory,
            tu,
            MemoryEntryCreate(
                memory_type=MemoryType.CONTEXT,
                memory_key=_scoped_key(_DRAFT_KEY, ctx),
                value=draft_context_to_storage(draft),
                importance=1.0,
            ),
        )
        await self.add_draft_expense_to_list(ctx, draft)

    async def add_draft_expense_to_list(
        self,
        ctx: SessionContext,
        draft: DraftExpenseContext,
    ) -> None:
        """Track multiple draft bills per chat session (multi-file / multi-intent)."""
        existing = await self.get_draft_expenses(ctx)
        merged: List[DraftExpenseContext] = []
        if draft.expense_id:
            replaced = False
            for item in existing:
                if item.expense_id == draft.expense_id:
                    merged.append(draft)
                    replaced = True
                else:
                    merged.append(item)
            if not replaced:
                merged.append(draft)
        else:
            merged = [*existing, draft]
        payload = [draft_context_to_storage(d) for d in merged]
        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        await asyncio.to_thread(
            self._repo.save_memory,
            tu,
            MemoryEntryCreate(
                memory_type=MemoryType.CONTEXT,
                memory_key=_scoped_key(_DRAFTS_LIST_KEY, ctx),
                value={"drafts": payload},
                importance=1.0,
            ),
        )

    async def get_draft_expenses(self, ctx: SessionContext) -> List[DraftExpenseContext]:
        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        key = _scoped_key(_DRAFTS_LIST_KEY, ctx)
        rows = await asyncio.to_thread(self._repo.fetch_memories, tu, limit=20)
        for row in rows:
            if row.memory_key == key:
                raw = (row.value or {}).get("drafts") or []
                return [DraftExpenseContext.model_validate(item) for item in raw]
        active = await self.get_draft_expense(ctx)
        return [active] if active else []

    async def clear_draft_expense(self, ctx: SessionContext) -> None:
        if self.redis_available:
            try:
                await self._redis.clear_draft_expense(ctx)
            except Exception as exc:
                logger.warning("Redis draft clear failed: %s", exc)

    async def get_draft_expense(self, ctx: SessionContext) -> Optional[DraftExpenseContext]:
        if self.redis_available:
            try:
                draft = await self._redis.get_draft_expense(ctx)
                if draft:
                    return draft
            except Exception as exc:
                logger.warning("Redis draft read failed: %s", exc)

        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        key = _scoped_key(_DRAFT_KEY, ctx)
        rows = await asyncio.to_thread(self._repo.fetch_memories, tu, limit=20)
        for row in rows:
            if row.memory_key == key:
                return DraftExpenseContext.model_validate(row.value or {})
        return None

    async def set_pending_intent(
        self,
        ctx: SessionContext,
        intent: PendingIntent,
        *,
        ttl: Optional[int] = None,
    ) -> None:
        if self.redis_available:
            try:
                await self._redis.set_pending_intent(ctx, intent, ttl=ttl)
                return
            except Exception as exc:
                logger.warning("Redis intent cache failed: %s", exc)

        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        await asyncio.to_thread(
            self._repo.save_memory,
            tu,
            MemoryEntryCreate(
                memory_type=MemoryType.CONTEXT,
                memory_key=_scoped_key(_INTENT_KEY, ctx),
                value=intent.model_dump(mode="json"),
                importance=1.0,
            ),
        )

    async def get_pending_intent(self, ctx: SessionContext) -> Optional[PendingIntent]:
        if self.redis_available:
            try:
                intent = await self._redis.get_pending_intent(ctx)
                if intent:
                    return intent
            except Exception as exc:
                logger.warning("Redis intent read failed: %s", exc)

        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        key = _scoped_key(_INTENT_KEY, ctx)
        rows = await asyncio.to_thread(self._repo.fetch_memories, tu, limit=20)
        for row in rows:
            if row.memory_key == key:
                return PendingIntent.model_validate(row.value or {})
        return None

    async def set_workflow_state(
        self,
        ctx: SessionContext,
        state: ConversationWorkflowState,
        *,
        ttl: Optional[int] = None,
    ) -> None:
        if self.redis_available:
            try:
                await self._redis.set_workflow_state(ctx, state, ttl=ttl)
                return
            except Exception as exc:
                logger.warning("Redis workflow cache failed: %s", exc)

        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        await asyncio.to_thread(
            self._repo.save_memory,
            tu,
            MemoryEntryCreate(
                memory_type=MemoryType.WORKFLOW,
                memory_key=_scoped_key(_WORKFLOW_KEY, ctx),
                value=state.model_dump(mode="json"),
                importance=1.0,
            ),
        )

    async def get_workflow_state(self, ctx: SessionContext) -> Optional[ConversationWorkflowState]:
        if self.redis_available:
            try:
                state = await self._redis.get_workflow_state(ctx)
                if state:
                    return state
            except Exception as exc:
                logger.warning("Redis workflow read failed: %s", exc)

        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        key = _scoped_key(_WORKFLOW_KEY, ctx)
        rows = await asyncio.to_thread(self._repo.fetch_memories, tu, limit=20)
        for row in rows:
            if row.memory_key == key:
                return ConversationWorkflowState.model_validate(row.value or {})
        return None

    async def clear_workflow_state(self, ctx: SessionContext) -> None:
        if self.redis_available:
            try:
                await self._redis.clear_workflow_state(ctx)
            except Exception as exc:
                logger.warning("Redis workflow clear failed: %s", exc)

    async def clear_pending_intent(self, ctx: SessionContext) -> None:
        if self.redis_available:
            try:
                await self._redis.clear_pending_intent(ctx)
            except Exception as exc:
                logger.warning("Redis intent clear failed: %s", exc)

    async def clear_session_state(self, ctx: SessionContext) -> None:
        """Clear Redis cache and Postgres-scoped session memory for this session."""
        await self.clear_draft_expense(ctx)
        await self.clear_pending_intent(ctx)
        await self.clear_workflow_state(ctx)
        if self.redis_available:
            try:
                await self._redis.clear_session_cache(ctx)
            except Exception as exc:
                logger.warning("Redis session cache clear failed: %s", exc)
        await asyncio.to_thread(self._repo.delete_session_scoped_memories, ctx)
