"""Memory service: conversations, context, long-term memory, summaries, compression."""

import asyncio

import logging

from typing import List, Optional



from app.ai.memory.context_compressor import ContextCompressor

from app.ai.memory.resilient_store import ResilientMemoryStore

from app.ai.memory.repository import AIRepository

from app.ai.memory.token_budget import TokenBudgetManager

from app.ai.prompts.system import SUMMARY_SYSTEM_PROMPT

from app.ai.sanitization import sanitize_prompt, sanitize_response

from app.ai.schemas.common import SessionContext, TenantUserContext

from app.ai.schemas.conversation import (

    ConversationMessageCreate,

    ConversationMessageOut,

    RecentContextOut,

)

from app.ai.schemas.memory import DraftExpenseContext, MemoryEntryCreate, MemoryEntryOut, PendingIntent

from app.ai.security import validate_user_message

from app.ai.services.audit_service import AuditService

from app.ai.services.openai_service import OpenAIService

from app.config import settings



logger = logging.getLogger(__name__)





class MemoryService:

    """Coordinates PostgreSQL memory and resilient session state (Redis cache optional)."""



    def __init__(

        self,

        repository: AIRepository,

        memory_store: ResilientMemoryStore,

        openai_service: OpenAIService,

        audit_service: AuditService,

        token_budget: Optional[TokenBudgetManager] = None,

    ):

        self._repo = repository

        self._store = memory_store

        self._openai = openai_service

        self._audit = audit_service

        self._compressor = ContextCompressor()

        self._token_budget = token_budget or TokenBudgetManager()



    async def save_conversation(

        self,

        ctx: SessionContext,

        message: ConversationMessageCreate,

    ) -> ConversationMessageOut:

        if message.role.value == "user":

            validate_user_message(message.content)



        row = await asyncio.to_thread(self._repo.save_conversation_message, ctx, message)
        await self._store.append_session_message(
            ctx,
            {
                "role": message.role.value,
                "content": row.content,
                "token_count": message.token_count,
            },
        )

        return ConversationMessageOut(

            id=row.id,

            role=row.role,

            content=row.content,

            metadata=row.metadata_ or {},

            token_count=row.token_count or 0,

            created_at=row.created_at,

        )



    async def fetch_recent_context(

        self,

        ctx: SessionContext,

        *,

        limit: Optional[int] = None,

    ) -> RecentContextOut:

        limit = limit or settings.ai_recent_message_limit

        messages = await asyncio.to_thread(self._repo.fetch_recent_messages, ctx, limit=limit)

        summary_row = await asyncio.to_thread(self._repo.fetch_latest_summary, ctx)

        compressed = False



        if len(messages) >= settings.ai_summary_trigger_message_count:

            messages, digest = self._compressor.compress_messages(messages)

            compressed = bool(digest)



        return RecentContextOut(

            session_id=ctx.session_id,

            messages=[

                ConversationMessageOut(

                    id=m.id,

                    role=m.role,

                    content=m.content,

                    metadata=m.metadata_ or {},

                    token_count=m.token_count or 0,

                    created_at=m.created_at,

                )

                for m in messages

            ],

            summary=summary_row.summary_text if summary_row else None,

            compressed=compressed,

        )



    def build_messages_for_llm(

        self,

        *,

        system_prompt: str,

        context: RecentContextOut,

    ) -> List[dict]:

        """Build and trim message list for OpenAI within token budget."""

        messages: List[dict] = [{"role": "system", "content": system_prompt}]

        if context.summary:

            messages.append({"role": "system", "content": f"Session summary:\n{context.summary}"})

        for msg in context.messages:

            messages.append({"role": msg.role, "content": msg.content})

        trimmed, _ = self._token_budget.trim_messages(messages)

        return trimmed



    async def save_long_term_memory(

        self,

        ctx: TenantUserContext,

        entry: MemoryEntryCreate,

    ) -> MemoryEntryOut:

        entry.value = sanitize_prompt(entry.value)  # type: ignore[assignment]

        row = await asyncio.to_thread(self._repo.save_memory, ctx, entry)

        return MemoryEntryOut(

            id=row.id,

            memory_type=row.memory_type,

            memory_key=row.memory_key,

            value=row.value or {},

            importance=row.importance,

            expires_at=row.expires_at,

            created_at=row.created_at,

            updated_at=row.updated_at,

        )



    async def fetch_long_term_memories(

        self,

        ctx: TenantUserContext,

        *,

        limit: int = 50,

    ) -> List[MemoryEntryOut]:

        rows = await asyncio.to_thread(self._repo.fetch_memories, ctx, limit=limit)

        return [

            MemoryEntryOut(

                id=r.id,

                memory_type=r.memory_type,

                memory_key=r.memory_key,

                value=r.value or {},

                importance=r.importance,

                expires_at=r.expires_at,

                created_at=r.created_at,

                updated_at=r.updated_at,

            )

            for r in rows

        ]



    async def generate_summary(self, ctx: SessionContext) -> str:

        messages = await asyncio.to_thread(

            self._repo.fetch_recent_messages,

            ctx,

            limit=settings.ai_summary_trigger_message_count,

        )

        tokens_before = self._compressor.estimate_tokens(messages)

        conversation_text = "\n".join(f"[{m.role}] {m.content}" for m in messages)



        try:

            summary_text, usage, latency_ms = await self._openai.generate_summary(

                conversation_text,

                SUMMARY_SYSTEM_PROMPT,

            )

            summary_text = sanitize_response(summary_text)

            if not isinstance(summary_text, str):

                summary_text = "Summary unavailable."

            self._audit.log_summary(

                TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id),

                session_id=ctx.session_id,

                model=self._openai.model,

                token_usage=usage,

                latency_ms=latency_ms,

            )

        except Exception as exc:

            logger.warning("Summary generation failed, using fallback: %s", exc)

            _, digest = self._compressor.compress_messages(messages, keep_recent=5)

            summary_text = digest or "No summary available."

            if isinstance(summary_text, str):

                summary_text = sanitize_response(summary_text)

            latency_ms = 0



        tokens_after = max(1, len(str(summary_text)) // 4)

        await asyncio.to_thread(

            self._repo.save_summary,

            ctx,

            summary_text=str(summary_text),

            token_count_before=tokens_before,

            token_count_after=tokens_after,

            model=self._openai.model,

        )

        return str(summary_text)



    async def compress_context_if_needed(self, ctx: SessionContext) -> Optional[str]:

        messages = await asyncio.to_thread(

            self._repo.fetch_recent_messages,

            ctx,

            limit=settings.ai_summary_trigger_message_count + 10,

        )

        if len(messages) < settings.ai_summary_trigger_message_count:

            return None

        return await self.generate_summary(ctx)



    async def get_draft_expense(self, ctx: SessionContext) -> Optional[DraftExpenseContext]:
        return await self._store.get_draft_expense(ctx)

    async def set_draft_expense(self, ctx: SessionContext, draft: DraftExpenseContext) -> None:
        await self._store.set_draft_expense(ctx, draft)

    async def clear_draft_expense(self, ctx: SessionContext) -> None:
        if hasattr(self._store, "clear_draft_expense"):
            await self._store.clear_draft_expense(ctx)

    async def get_pending_intent(self, ctx: SessionContext) -> Optional[PendingIntent]:
        return await self._store.get_pending_intent(ctx)

    async def set_pending_intent(self, ctx: SessionContext, intent: PendingIntent) -> None:
        await self._store.set_pending_intent(ctx, intent)

    async def clear_pending_intent(self, ctx: SessionContext) -> None:
        if hasattr(self._store, "clear_pending_intent"):
            await self._store.clear_pending_intent(ctx)

    async def get_workflow_state(self, ctx: SessionContext):
        from app.ai.schemas.workflow import ConversationWorkflowState
        return await self._store.get_workflow_state(ctx)

    async def set_workflow_state(self, ctx: SessionContext, state) -> None:
        await self._store.set_workflow_state(ctx, state)

    async def clear_workflow_state(self, ctx: SessionContext) -> None:
        await self._store.clear_workflow_state(ctx)

    async def clear_session_state(self, ctx: SessionContext) -> None:
        await self._store.clear_session_state(ctx)

    async def purge_expired_memories(self, ctx: TenantUserContext) -> int:
        return await asyncio.to_thread(self._repo.purge_expired_memories, ctx)

    def needs_compression(self, messages: List[dict]) -> bool:
        return self._token_budget.needs_compression(messages)


