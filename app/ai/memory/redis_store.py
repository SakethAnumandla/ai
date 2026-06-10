"""Optional Redis cache for ephemeral AI session state (Postgres is source of truth)."""
import json
import logging
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis

from app.ai.schemas.common import SessionContext
from app.ai.schemas.memory import DraftExpenseContext, PendingIntent
from app.ai.schemas.workflow import ConversationWorkflowState
from app.config import settings

logger = logging.getLogger(__name__)


class RedisMemoryStore:
    """Async Redis layer with TTL support. No-op when Redis is disabled or unreachable."""

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or settings.redis_url
        self._client: Optional[aioredis.Redis] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    async def connect(self) -> bool:
        """Best-effort connect. Returns True when connected; never raises."""
        if not settings.redis_enabled:
            self._connected = False
            return False
        if self._client is None:
            self._client = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        try:
            await self._client.ping()
            self._connected = True
            logger.info("Redis AI cache connected")
            return True
        except Exception as exc:
            self._connected = False
            logger.warning("Redis unavailable, using PostgreSQL only: %s", exc)
            return False

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    def _client_or_raise(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("RedisMemoryStore not connected; call connect() first")
        return self._client

    @staticmethod
    def _session_key(ctx: SessionContext) -> str:
        return f"ai:session:{ctx.tenant_id}:{ctx.user_id}:{ctx.session_id}:messages"

    @staticmethod
    def _draft_key(ctx: SessionContext) -> str:
        return f"ai:draft:{ctx.tenant_id}:{ctx.user_id}:{ctx.session_id}"

    @staticmethod
    def _intent_key(ctx: SessionContext) -> str:
        return f"ai:intent:{ctx.tenant_id}:{ctx.user_id}:{ctx.session_id}"

    @staticmethod
    def _workflow_key(ctx: SessionContext) -> str:
        return f"ai:workflow:{ctx.tenant_id}:{ctx.user_id}:{ctx.session_id}"

    async def append_session_message(
        self,
        ctx: SessionContext,
        message: Dict[str, Any],
        *,
        ttl: Optional[int] = None,
    ) -> None:
        client = self._client_or_raise()
        key = self._session_key(ctx)
        ttl = ttl or settings.ai_session_ttl_seconds
        await client.rpush(key, json.dumps(message))
        await client.expire(key, ttl)

    async def get_session_messages(
        self,
        ctx: SessionContext,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        client = self._client_or_raise()
        key = self._session_key(ctx)
        raw = await client.lrange(key, -limit, -1)
        return [json.loads(item) for item in raw]

    async def set_draft_expense(
        self,
        ctx: SessionContext,
        draft: DraftExpenseContext,
        *,
        ttl: Optional[int] = None,
    ) -> None:
        client = self._client_or_raise()
        key = self._draft_key(ctx)
        ttl = ttl or settings.ai_draft_expense_ttl_seconds
        await client.set(key, draft.model_dump_json(), ex=ttl)

    async def get_draft_expense(self, ctx: SessionContext) -> Optional[DraftExpenseContext]:
        client = self._client_or_raise()
        raw = await client.get(self._draft_key(ctx))
        if not raw:
            return None
        return DraftExpenseContext.model_validate_json(raw)

    async def clear_draft_expense(self, ctx: SessionContext) -> None:
        client = self._client_or_raise()
        await client.delete(self._draft_key(ctx))

    async def set_pending_intent(
        self,
        ctx: SessionContext,
        intent: PendingIntent,
        *,
        ttl: Optional[int] = None,
    ) -> None:
        client = self._client_or_raise()
        key = self._intent_key(ctx)
        ttl = ttl or settings.ai_pending_intent_ttl_seconds
        await client.set(key, intent.model_dump_json(), ex=ttl)

    async def get_pending_intent(self, ctx: SessionContext) -> Optional[PendingIntent]:
        client = self._client_or_raise()
        raw = await client.get(self._intent_key(ctx))
        if not raw:
            return None
        return PendingIntent.model_validate_json(raw)

    async def clear_pending_intent(self, ctx: SessionContext) -> None:
        client = self._client_or_raise()
        await client.delete(self._intent_key(ctx))

    async def set_workflow_state(
        self,
        ctx: SessionContext,
        state: ConversationWorkflowState,
        *,
        ttl: Optional[int] = None,
    ) -> None:
        client = self._client_or_raise()
        ttl = ttl or settings.ai_workflow_state_ttl_seconds
        await client.set(self._workflow_key(ctx), state.model_dump_json(), ex=ttl)

    async def get_workflow_state(self, ctx: SessionContext) -> Optional[ConversationWorkflowState]:
        client = self._client_or_raise()
        raw = await client.get(self._workflow_key(ctx))
        if not raw:
            return None
        return ConversationWorkflowState.model_validate_json(raw)

    async def clear_workflow_state(self, ctx: SessionContext) -> None:
        client = self._client_or_raise()
        await client.delete(self._workflow_key(ctx))

    async def clear_session_cache(self, ctx: SessionContext) -> None:
        """Remove Redis keys for this chat session (messages, draft, intent, workflow)."""
        client = self._client_or_raise()
        keys = [
            self._session_key(ctx),
            self._draft_key(ctx),
            self._intent_key(ctx),
            self._workflow_key(ctx),
        ]
        if keys:
            await client.delete(*keys)
