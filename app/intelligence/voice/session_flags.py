"""Redis-backed voice session flags."""
import json
from typing import Optional

from app.ai.memory.redis_store import RedisMemoryStore
from app.ai.schemas.common import SessionContext


class VoiceSessionFlags:
    KEY_PREFIX = "ai:voice_session:"

    @classmethod
    def _key(cls, ctx: SessionContext) -> str:
        return f"{cls.KEY_PREFIX}{ctx.tenant_id}:{ctx.user_id}:{ctx.session_id}"

    @classmethod
    async def mark_voice_originated(cls, ctx: SessionContext, *, ttl: int = 3600) -> None:
        store = RedisMemoryStore()
        try:
            await store.connect()
            client = store._client_or_raise()
            await client.set(
                cls._key(ctx),
                json.dumps({"voice_originated": True, "interaction_source": "voice"}),
                ex=ttl,
            )
        except Exception:
            pass

    @classmethod
    async def get_metadata(cls, ctx: SessionContext) -> dict:
        store = RedisMemoryStore()
        try:
            await store.connect()
            client = store._client_or_raise()
            raw = await client.get(cls._key(ctx))
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return {}

    @classmethod
    async def is_voice_originated(cls, ctx: SessionContext) -> bool:
        meta = await cls.get_metadata(ctx)
        return bool(meta.get("voice_originated"))
