"""Per-session locking to prevent concurrent conflicting AI requests."""
import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.ai.schemas.common import SessionContext

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "ai:lock:"
_LOCK_TTL_SECONDS = 120


class SessionLockManager:
    """
    Hybrid locking: in-process asyncio.Lock per session + optional Redis distributed lock.
    """

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._local_locks: dict[str, asyncio.Lock] = {}
        self._meta = asyncio.Lock()
        self._redis = redis_client

    def _key(self, ctx: SessionContext) -> str:
        return f"{ctx.tenant_id}:{ctx.user_id}:{ctx.session_id}"

    async def _get_local_lock(self, key: str) -> asyncio.Lock:
        async with self._meta:
            if key not in self._local_locks:
                self._local_locks[key] = asyncio.Lock()
            return self._local_locks[key]

    async def acquire(self, ctx: SessionContext) -> None:
        key = self._key(ctx)
        local = await self._get_local_lock(key)
        await local.acquire()
        if self._redis:
            try:
                redis_key = f"{_LOCK_PREFIX}{key}"
                acquired = await self._redis.set(
                    redis_key, "1", nx=True, ex=_LOCK_TTL_SECONDS
                )
                if not acquired:
                    local.release()
                    raise SessionLockError(
                        "Another request is processing this session. Please retry."
                    )
            except SessionLockError:
                raise
            except Exception as exc:
                logger.warning("Redis session lock unavailable, using local only: %s", exc)

    async def release(self, ctx: SessionContext) -> None:
        key = self._key(ctx)
        if self._redis:
            try:
                await self._redis.delete(f"{_LOCK_PREFIX}{key}")
            except Exception as exc:
                logger.warning("Redis session lock release failed: %s", exc)
        local = await self._get_local_lock(key)
        if local.locked():
            local.release()


class SessionLockError(Exception):
    pass


class session_lock:
    """Async context manager for session-scoped locks."""

    def __init__(self, manager: SessionLockManager, ctx: SessionContext):
        self._manager = manager
        self._ctx = ctx

    async def __aenter__(self) -> SessionContext:
        await self._manager.acquire(self._ctx)
        return self._ctx

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._manager.release(self._ctx)
