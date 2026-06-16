"""Continue active expense workflows before general chat routing."""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.chat_ui import build_workflow_preview_card
from app.ai.conversation.expense_manage import ExpenseManageWorkflow
from app.ai.conversation.state_machine import (
    ConversationStateMachine,
    _POST_SAVE_FOLLOWUP_QUESTION,
    _POST_SAVE_FOLLOWUP_SLOT,
    _POST_SAVE_THANK_YOU,
)
from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.schemas.memory import DraftExpenseContext, PendingIntent
from app.ai.schemas.workflow import ConversationWorkflowState, WorkflowScope, WorkflowType
from app.ai.services.memory_service import MemoryService
from app.ai.workflow.draft_persist import persist_workflow_draft
from app.ai.workflow.draft_summary import format_draft_summary
from app.ai.schemas.chat_ui import workflow_summary_actions
from app.ai.workflow.slot_parser import (
    infer_food_sub_category,
    is_workflow_slot_message,
    parse_slot_updates,
    sanitize_sub_category,
)
from app.models import User

logger = logging.getLogger(__name__)


@dataclass
class WorkflowContinueResult:
    handled: bool = False
    message: Optional[str] = None
    execute_tool: Optional[str] = None
    execute_arguments: Dict[str, Any] = field(default_factory=dict)
    ui_actions: Optional[List[Any]] = None
    expense_previews: Optional[List[Any]] = None
    category_picker: Optional[Any] = None


class WorkflowEngine:
    def __init__(
        self,
        memory: MemoryService,
        db: Optional[Session] = None,
        state_machine: Optional[ConversationStateMachine] = None,
    ):
        self._memory = memory
        self._db = db
        self._sm = state_machine or ConversationStateMachine()

    async def get_active_context(
        self, ctx: SessionContext
    ) -> tuple[Optional[ConversationWorkflowState], Optional[DraftExpenseContext], Optional[PendingIntent]]:
        state = await self._memory.get_workflow_state(ctx)
        draft = await self._memory.get_draft_expense(ctx)
        pending = await self._memory.get_pending_intent(ctx)
        return state, draft, pending

    def log_active_context(
        self,
        ctx: SessionContext,
        *,
        state: Optional[ConversationWorkflowState],
        draft: Optional[DraftExpenseContext],
        pending: Optional[PendingIntent],
    ) -> None:
        logger.info(
            "workflow.context session_id=%s user_id=%s tenant_id=%s "
            "active_workflow=%s draft=%s pending_intent=%s",
            ctx.session_id,
            ctx.user_id,
            ctx.tenant_id,
            state.workflow_type.value if state else None,
            draft.model_dump() if draft else None,
            pending.intent_type if pending else None,
        )

    async def continue_workflow(
        self,
        ctx: SessionContext,
        user_content: str,
        *,
        prefill: Optional[Dict[str, Any]] = None,
        user: Optional[User] = None,
    ) -> WorkflowContinueResult:
        """
        Apply slot updates or advance slot-filling for an active expense workflow.
        Returns assistant message if handled, else None.
        """
        state, draft, pending = await self.get_active_context(ctx)
        self.log_active_context(ctx, state=state, draft=draft, pending=pending)

        if state is None and draft and (draft.fields_pending or self._draft_incomplete(draft)):
            state = self._sm.start_from_draft(draft, session_id=ctx.session_id)
            logger.info("workflow.loaded from_draft session_id=%s", ctx.session_id)

        if state is None and pending and pending.intent_type == "expense_create":
            slots = dict(pending.parameters or {})
            state = ConversationWorkflowState(
                workflow_type=WorkflowType.EXPENSE_CREATE,
                scope=WorkflowScope.EXPENSE,
                slots=slots,
                pending_slots=list(slots.get("fields_pending") or []),
                session_id=ctx.session_id,
            )
            logger.info("workflow.loaded from_pending_intent session_id=%s", ctx.session_id)

        if state is None:
            return WorkflowContinueResult(handled=False)

        if state.slots.get(_POST_SAVE_FOLLOWUP_SLOT):
            return await self._handle_post_save_followup(ctx, user_content, state)

        if state.workflow_type in (WorkflowType.EXPENSE_DELETE, WorkflowType.EXPENSE_UPDATE):
            if self._db is None:
                return WorkflowContinueResult(handled=False)
            manage = ExpenseManageWorkflow(self._db)
            mg_result = manage.process_turn(user_content, state)
            if mg_result.handled:
                return await self._finalize_manage_result(ctx, mg_result)
            return WorkflowContinueResult(handled=False)

        updates = parse_slot_updates(user_content)
        if updates:
            if updates.get("sub_category"):
                if updates.get("sub_category_raw"):
                    state.slots["sub_category_raw"] = updates["sub_category_raw"]
                mapped = sanitize_sub_category(
                    state.slots.get("main_category"),
                    updates["sub_category"],
                    vendor_name=state.slots.get("vendor_name"),
                    bill_name=state.slots.get("bill_name"),
                )
                if mapped:
                    updates["sub_category"] = mapped
                else:
                    updates.pop("sub_category", None)
            for key, value in updates.items():
                if key.endswith("_raw") or value is None:
                    continue
                state.fill_slot(key, value)
            await self._persist(ctx, state)
            logger.info(
                "workflow.slot_filled session_id=%s updates=%s remaining=%s",
                ctx.session_id,
                updates,
                state.pending_slots,
            )
            if not state.pending_slots:
                if user and self._db:
                    state, _ = persist_workflow_draft(
                        self._db, user, state, company_id=ctx.scoped_company_id
                    )
                await self._persist(ctx, state)
                attach_result = self._sm._prompt_attachment_or_submit(state, user_content)
                if attach_result.updated_state:
                    state = attach_result.updated_state
                    await self._persist(ctx, state)
                synced = state
                preview = self._preview_for_state(synced)
                eid = synced.expense_id or synced.slots.get("expense_id")
                return WorkflowContinueResult(
                    handled=True,
                    message=attach_result.assistant_message or format_draft_summary(synced.slots),
                    ui_actions=attach_result.ui_actions
                    or workflow_summary_actions(int(eid) if eid else None),
                    expense_previews=[preview] if preview else None,
                )
            synced = await self._sync_draft_if_needed(ctx, state, user=user)
            preview = self._preview_for_state(synced)
            return WorkflowContinueResult(
                handled=True,
                message=format_draft_summary(synced.slots, intro="Updated draft"),
                expense_previews=[preview] if preview else None,
            )

        sm_result = self._sm.process_turn(
            user_content, state, session_id=ctx.session_id, prefill=prefill
        )
        if sm_result.handled:
            return await self._finalize_sm_result(ctx, sm_result, user=user)

        if is_workflow_slot_message(user_content):
            return WorkflowContinueResult(
                handled=True,
                message=format_draft_summary(state.slots, intro="Here's what I have so far"),
            )

        return WorkflowContinueResult(handled=False)

    async def save_pending_expense(
        self,
        ctx: SessionContext,
        slots: Dict[str, Any],
        *,
        fields_pending: Optional[list] = None,
    ) -> None:
        pending_fields = fields_pending or []
        if slots.get("main_category") == "food":
            inferred = infer_food_sub_category(
                vendor_name=slots.get("vendor_name"),
                bill_name=slots.get("bill_name"),
            )
            if inferred:
                slots["sub_category"] = inferred
        pending_fields = [f for f in pending_fields if f != "sub_category"]

        state = ConversationWorkflowState(
            workflow_type=WorkflowType.EXPENSE_CREATE,
            scope=WorkflowScope.EXPENSE,
            slots=slots,
            pending_slots=pending_fields,
            session_id=ctx.session_id,
        )
        await self._persist(ctx, state)
        await self._memory.set_pending_intent(
            ctx,
            PendingIntent(
                intent_type="expense_create",
                parameters={**slots, "fields_pending": pending_fields},
            ),
        )
        logger.info(
            "workflow.saved session_id=%s slots=%s pending=%s",
            ctx.session_id,
            slots,
            pending_fields,
        )

    @staticmethod
    def _draft_incomplete(draft: DraftExpenseContext) -> bool:
        return bool(
            draft.bill_amount
            or draft.vendor_name
            or draft.fields_pending
        )

    async def _handle_post_save_followup(
        self,
        ctx: SessionContext,
        user_content: str,
        state: ConversationWorkflowState,
    ) -> WorkflowContinueResult:
        from app.ai.conversation.post_save import is_post_save_accept, is_post_save_decline

        if is_post_save_decline(user_content):
            await self._memory.clear_workflow_state(ctx)
            await self._memory.clear_pending_intent(ctx)
            return WorkflowContinueResult(
                handled=True,
                message=_POST_SAVE_THANK_YOU,
            )
        if is_post_save_accept(user_content):
            await self._memory.clear_workflow_state(ctx)
            await self._memory.clear_pending_intent(ctx)
            return WorkflowContinueResult(
                handled=True,
                message="Sure — what would you like help with?",
            )
        return WorkflowContinueResult(
            handled=True,
            message=_POST_SAVE_FOLLOWUP_QUESTION,
        )

    @staticmethod
    def post_save_followup_state(*, session_id: str) -> ConversationWorkflowState:
        return ConversationWorkflowState(
            workflow_type=WorkflowType.EXPENSE_CONTINUE,
            scope=WorkflowScope.GENERAL,
            slots={_POST_SAVE_FOLLOWUP_SLOT: True},
            session_id=session_id,
        )

    async def persist_workflow_state(
        self,
        ctx: SessionContext,
        state: ConversationWorkflowState,
    ) -> None:
        await self._persist(ctx, state)

    async def _persist(
        self,
        ctx: SessionContext,
        state: ConversationWorkflowState,
    ) -> None:
        state.session_id = ctx.session_id
        await self._memory.set_workflow_state(ctx, state)
        intent_type = "expense_create"
        if state.workflow_type == WorkflowType.EXPENSE_DELETE:
            intent_type = "expense_delete"
        elif state.workflow_type == WorkflowType.EXPENSE_UPDATE:
            intent_type = "expense_update"
        else:
            await self._memory.set_draft_expense(ctx, self._sm.state_to_draft(state))
        await self._memory.set_pending_intent(
            ctx,
            PendingIntent(
                intent_type=intent_type,
                parameters={
                    **state.slots,
                    "fields_pending": list(state.pending_slots),
                    "session_id": ctx.session_id,
                },
            ),
        )
        logger.info("workflow.persisted session_id=%s type=%s", ctx.session_id, intent_type)

    async def _finalize_manage_result(self, ctx, mg_result) -> WorkflowContinueResult:
        if mg_result.updated_state and not mg_result.clear_state:
            await self._persist(ctx, mg_result.updated_state)
        if mg_result.clear_state:
            await self._memory.clear_workflow_state(ctx)
            await self._memory.clear_pending_intent(ctx)

        if mg_result.ready_tool_name:
            return WorkflowContinueResult(
                handled=True,
                execute_tool=mg_result.ready_tool_name,
                execute_arguments=dict(mg_result.ready_arguments or {}),
            )
        if mg_result.assistant_message:
            return WorkflowContinueResult(
                handled=True,
                message=mg_result.assistant_message,
            )
        return WorkflowContinueResult(handled=False)

    async def _finalize_sm_result(
        self, ctx, sm_result, *, user: Optional[User] = None
    ) -> WorkflowContinueResult:
        state = sm_result.updated_state
        if state and sm_result.sync_draft and user and self._db is not None:
            state, _ = persist_workflow_draft(
                self._db, user, state, company_id=ctx.scoped_company_id
            )
            sm_result.updated_state = state

        if sm_result.updated_state:
            await self._persist(ctx, sm_result.updated_state)
            state = sm_result.updated_state

        preview = None
        if state and (state.expense_id or state.slots.get("expense_id")) and self._db:
            preview = self._preview_for_state(state)

        if sm_result.ready_tool_name:
            logger.info(
                "workflow.completed session_id=%s tool=%s",
                ctx.session_id,
                sm_result.ready_tool_name,
            )
            if sm_result.clear_state:
                await self._memory.clear_workflow_state(ctx)
                await self._memory.clear_pending_intent(ctx)
            return WorkflowContinueResult(
                handled=True,
                execute_tool=sm_result.ready_tool_name,
                execute_arguments=dict(sm_result.ready_arguments or {}),
            )

        if sm_result.assistant_message:
            return WorkflowContinueResult(
                handled=True,
                message=sm_result.assistant_message,
                ui_actions=sm_result.ui_actions,
                expense_previews=[preview] if preview else None,
                category_picker=getattr(sm_result, "category_picker", None),
            )

        if sm_result.updated_state and not sm_result.updated_state.pending_slots:
            return WorkflowContinueResult(
                handled=True,
                message=format_draft_summary(sm_result.updated_state.slots),
                ui_actions=sm_result.ui_actions,
                expense_previews=[preview] if preview else None,
                category_picker=getattr(sm_result, "category_picker", None),
            )

        return WorkflowContinueResult(handled=False)

    def _preview_for_state(self, state: ConversationWorkflowState):
        if not self._db:
            return None
        eid = state.expense_id or state.slots.get("expense_id")
        if not eid:
            return None
        return build_workflow_preview_card(
            self._db, expense_id=int(eid), slots=state.slots
        )

    async def _sync_draft_if_needed(
        self,
        ctx: SessionContext,
        state: ConversationWorkflowState,
        *,
        user: Optional[User] = None,
    ) -> ConversationWorkflowState:
        if not user or not self._db:
            return state
        if not state.slots.get("_awaiting_submit_confirm"):
            return state
        state, _ = persist_workflow_draft(
            self._db, user, state, company_id=ctx.scoped_company_id
        )
        await self._persist(ctx, state)
        return state
