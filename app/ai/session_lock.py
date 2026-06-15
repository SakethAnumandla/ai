"""Per-session locking to prevent concurrent conflicting AI requests."""
import asyncio

from app.ai.schemas.common import SessionContext


class SessionLockManager:
    """In-process asyncio.Lock per session."""

    def __init__(self) -> None:
        self._local_locks: dict[str, asyncio.Lock] = {}
        self._meta = asyncio.Lock()

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

    async def release(self, ctx: SessionContext) -> None:
        key = self._key(ctx)
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
