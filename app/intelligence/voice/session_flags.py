"""Postgres-backed voice session flags."""
import asyncio
from typing import Optional

from app.ai.memory.repository import AIRepository
from app.ai.models.entities import MemoryType
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.schemas.memory import MemoryEntryCreate
from app.database import SessionLocal

_VOICE_KEY = "voice_session:metadata"


class VoiceSessionFlags:
    @classmethod
    def _memory_key(cls, ctx: SessionContext) -> str:
        return f"{_VOICE_KEY}:{ctx.session_id}"

    @classmethod
    async def mark_voice_originated(cls, ctx: SessionContext) -> None:
        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        value = {"voice_originated": True, "interaction_source": "voice"}

        def _save() -> None:
            db = SessionLocal()
            try:
                repo = AIRepository(db)
                repo.save_memory(
                    tu,
                    MemoryEntryCreate(
                        memory_type=MemoryType.CONTEXT,
                        memory_key=cls._memory_key(ctx),
                        value=value,
                        importance=1.0,
                    ),
                )
            finally:
                db.close()

        await asyncio.to_thread(_save)

    @classmethod
    async def get_metadata(cls, ctx: SessionContext) -> dict:
        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)

        def _load() -> Optional[dict]:
            db = SessionLocal()
            try:
                repo = AIRepository(db)
                row = repo.fetch_memory_by_key(tu, cls._memory_key(ctx))
                if row and row.value is not None:
                    return row.value
            finally:
                db.close()
            return None

        raw = await asyncio.to_thread(_load)
        return raw or {}

    @classmethod
    async def is_voice_originated(cls, ctx: SessionContext) -> bool:
        meta = await cls.get_metadata(ctx)
        return bool(meta.get("voice_originated"))
