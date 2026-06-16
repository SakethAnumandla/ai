"""Session state in PostgreSQL (via AIRepository)."""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.ai.json_util import draft_context_to_storage
from app.ai.memory.repository import AIRepository
from app.ai.schemas.common import SessionContext
from app.ai.security import tenant_user_from_ctx
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
    """Persists draft expenses, pending intents, and workflow state in PostgreSQL."""

    def __init__(self, repository: AIRepository):
        self._repo = repository

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    def _tenant_user(self, ctx: SessionContext):
        return tenant_user_from_ctx(ctx)

    async def _delete_pg_key(self, ctx: SessionContext, base_key: str) -> None:
        tu = self._tenant_user(ctx)
        key = _scoped_key(base_key, ctx)
        await asyncio.to_thread(self._repo.delete_memory_by_key, tu, key)

    async def _fetch_pg_value(self, ctx: SessionContext, base_key: str) -> Optional[dict]:
        tu = self._tenant_user(ctx)
        key = _scoped_key(base_key, ctx)
        row = await asyncio.to_thread(self._repo.fetch_memory_by_key, tu, key)
        if row and row.value is not None:
            return row.value
        return None

    async def append_session_message(
        self,
        ctx: SessionContext,
        message: Dict[str, Any],
        *,
        ttl: Optional[int] = None,
    ) -> None:
        # Messages are persisted via AIRepository.save_conversation_message.
        return None

    async def get_session_messages(
        self,
        ctx: SessionContext,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
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
        tu = self._tenant_user(ctx)
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
        tu = self._tenant_user(ctx)
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
        raw = await self._fetch_pg_value(ctx, _DRAFTS_LIST_KEY)
        if raw:
            drafts = raw.get("drafts") or []
            return [DraftExpenseContext.model_validate(item) for item in drafts]
        active = await self.get_draft_expense(ctx)
        return [active] if active else []

    async def clear_draft_expense(self, ctx: SessionContext) -> None:
        await self._delete_pg_key(ctx, _DRAFT_KEY)
        await self._delete_pg_key(ctx, _DRAFTS_LIST_KEY)

    async def get_draft_expense(self, ctx: SessionContext) -> Optional[DraftExpenseContext]:
        raw = await self._fetch_pg_value(ctx, _DRAFT_KEY)
        if raw:
            return DraftExpenseContext.model_validate(raw)
        return None

    async def set_pending_intent(
        self,
        ctx: SessionContext,
        intent: PendingIntent,
        *,
        ttl: Optional[int] = None,
    ) -> None:
        tu = self._tenant_user(ctx)
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
        raw = await self._fetch_pg_value(ctx, _INTENT_KEY)
        if raw:
            return PendingIntent.model_validate(raw)
        return None

    async def set_workflow_state(
        self,
        ctx: SessionContext,
        state: ConversationWorkflowState,
        *,
        ttl: Optional[int] = None,
    ) -> None:
        tu = self._tenant_user(ctx)
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
        raw = await self._fetch_pg_value(ctx, _WORKFLOW_KEY)
        if raw:
            return ConversationWorkflowState.model_validate(raw)
        return None

    async def clear_workflow_state(self, ctx: SessionContext) -> None:
        await self._delete_pg_key(ctx, _WORKFLOW_KEY)

    async def clear_pending_intent(self, ctx: SessionContext) -> None:
        await self._delete_pg_key(ctx, _INTENT_KEY)

    async def clear_session_state(self, ctx: SessionContext) -> None:
        """Clear Postgres-scoped session memory for this session."""
        await self.clear_draft_expense(ctx)
        await self.clear_pending_intent(ctx)
        await self.clear_workflow_state(ctx)
        await asyncio.to_thread(self._repo.delete_session_scoped_memories, ctx)
