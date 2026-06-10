"""Memory decay — soft forgetting, stale workflow hygiene, hard expire for ephemeral only."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.ai.memory.audit import MemoryAuditService
from app.ai.memory.policy import MemoryPolicyService
from app.ai.memory.repository import AIRepository
from app.ai.memory.soft_forgetting import SoftForgettingEngine
from app.ai.models.entities import MemoryType
from app.ai.schemas.memory import MemoryEntryCreate
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.services.memory_service import MemoryService
from app.config import settings

logger = logging.getLogger(__name__)


def _memory_type_enum(memory_type: str) -> MemoryType:
    try:
        return MemoryType(memory_type)
    except ValueError:
        return MemoryType.CONTEXT


class MemoryDecayService:
    def __init__(
        self,
        repository: AIRepository,
        memory: MemoryService,
        *,
        policy: Optional[MemoryPolicyService] = None,
        audit: Optional[MemoryAuditService] = None,
    ):
        self._repo = repository
        self._memory = memory
        self._soft = SoftForgettingEngine()
        self._policy = policy
        self._audit = audit

    async def run_session_hygiene(self, ctx: SessionContext) -> dict:
        tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
        stats = {
            "expired_memories": 0,
            "soft_decayed": 0,
            "stale_intent_cleared": False,
            "stale_workflow_cleared": False,
        }

        stats["expired_memories"] = await self._memory.purge_expired_memories(tu)

        intent = await self._memory.get_pending_intent(ctx)
        if intent:
            created = intent.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created > timedelta(hours=settings.ai_stale_intent_hours):
                await self._memory.clear_pending_intent(ctx)
                stats["stale_intent_cleared"] = True

        state = await self._memory.get_workflow_state(ctx)
        if state:
            updated = state.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - updated
            if age > timedelta(seconds=settings.ai_workflow_state_ttl_seconds):
                await self._memory.clear_workflow_state(ctx)
                stats["stale_workflow_cleared"] = True

        stats["soft_decayed"] = await asyncio.to_thread(self._apply_soft_forgetting, tu)

        if any(v for k, v in stats.items() if v):
            logger.info("memory.decay", extra={"tenant_id": ctx.tenant_id, **stats})
        return stats

    def _apply_soft_forgetting(self, ctx: TenantUserContext) -> int:
        if self._policy and not self._policy.get_effective(ctx.tenant_id).can_persist_long_term():
            return 0

        rows = self._repo.fetch_memories(ctx, limit=150)
        changed = 0
        for row in rows:
            ref = row.updated_at or row.created_at
            decayed = self._soft.decayed_importance(row.importance or 0.5, last_used_at=ref)
            if abs(decayed - (row.importance or 0)) < 0.01:
                continue

            if self._soft.should_hard_expire(decayed, row.memory_type):
                self._repo.save_memory(
                    ctx,
                    MemoryEntryCreate(
                        memory_type=_memory_type_enum(row.memory_type),
                        memory_key=row.memory_key,
                        value=row.value or {},
                        importance=row.importance or 0.5,
                        expires_at=datetime.now(timezone.utc),
                    ),
                )
            else:
                conf_before = row.importance
                self._repo.update_importance(row.id, decayed)
                value = dict(row.value or {})
                if row.memory_type == "preference" and "primary_confidence" in value:
                    value["primary_confidence"] = min(
                        float(value.get("primary_confidence", decayed)),
                        decayed,
                    )
                    for cand in (value.get("candidates") or {}).values():
                        if isinstance(cand, dict) and "confidence" in cand:
                            cand["confidence"] = min(
                                float(cand["confidence"]),
                                decayed + 0.1,
                            )
                    row.value = value
                    self._repo.db.commit()
                if self._audit and row.memory_type == "preference":
                    self._audit.record(
                        ctx,
                        memory_key=row.memory_key,
                        change_type="soft_decay",
                        source="memory_decay_service",
                        before={"importance": conf_before},
                        after={"importance": decayed, "value": value},
                        confidence_before=conf_before,
                        confidence_after=decayed,
                    )
            changed += 1
        return changed
