"""AI copilot API."""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.ai.manual_chat_upload import attach_receipt_to_manual_workflow
from app.ai.chat_attachments import (
    build_chat_attachment_bundle,
    build_chat_attachment_bundle_from_file_infos,
)
from app.ai.conversation.state_machine import ConversationStateMachine, _GOT_IT_AFTER_ATTACHMENT
from app.ai.dependencies import (
    get_ai_memory_service,
    get_ai_orchestrator,
    get_dead_letter_service,
)
from app.ai.dead_letter.service import DeadLetterQueueService
from app.ai.orchestrator.base import AIOrchestrator
from app.ai.receipt_chat import (
    merge_multimodal_with_draft_context,
    run_chat_receipt_scans,
)
from app.ai.schemas.chat import ChatRequest, ChatResponse
from app.ai.schemas.memory import PendingIntent
from app.ai.schemas.chat_ui import ChatUIAction, ExpensePreviewCard, CategoryPickerPayload
from app.ai.models.entities import AIConversation, ConversationRole
from app.ai.schemas.conversation import ConversationMessageCreate, ConversationMessageOut
from app.ai.security import build_session_context_from_scope, assert_chat_session_access
from app.ai.services.memory_service import MemoryService
from app.config import settings
from app.database import get_db
from app.deps.scope import ExpenseScope, get_expense_scope
from app.models import AIChatSession, User
from sqlalchemy import desc, func
from app.utils.file_upload import process_multiple_files
from app.utils.async_io import run_blocking

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


def _user(db: Session, scope: ExpenseScope) -> User:
    """Load ORM user for orchestrator (welcome, tools, role prompts)."""
    row = db.query(User).filter(User.id == scope.user_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {scope.user_id} not found",
        )
    return row


def _ctx(scope: ExpenseScope, session_id: str):
    return build_session_context_from_scope(scope, session_id)


def _guard_session(db: Session, scope: ExpenseScope, session_id: str) -> None:
    assert_chat_session_access(
        db,
        company_id=scope.company_id,
        user_id=scope.user_id,
        session_id=session_id,
    )


def _attachments_enabled(
    ui_actions: Optional[List[ChatUIAction]] = None,
    *,
    explicit: bool = False,
) -> bool:
    if explicit:
        return True
    if ui_actions:
        return any(a.action == "attach" for a in ui_actions)
    return False


def _build_chat_response(
    result: dict,
    *,
    expense_previews: Optional[List[ExpensePreviewCard]] = None,
    ui_actions: Optional[List[ChatUIAction]] = None,
    attachments_enabled: Optional[bool] = None,
    category_picker: Optional[CategoryPickerPayload] = None,
) -> ChatResponse:
    msg = result["message"]
    actions = list(ui_actions) if ui_actions else None
    if actions is not None and not actions:
        actions = None
    attach_flag = (
        attachments_enabled
        if attachments_enabled is not None
        else _attachments_enabled(actions)
    )
    return ChatResponse(
        message=(
            msg
            if isinstance(msg, ConversationMessageOut)
            else ConversationMessageOut.model_validate(msg)
        ),
        session_id=result["session_id"],
        request_id=result.get("request_id"),
        trace_id=result.get("trace_id"),
        classification=result.get("classification"),
        requires_confirmation=bool(result.get("requires_confirmation")),
        confirmation_token=result.get("confirmation_token"),
        tool_results=result.get("tool_results"),
        attachments_enabled=attach_flag,
        expense_previews=expense_previews,
        ui_actions=actions,
        category_picker=category_picker or result.get("category_picker"),
    )


def _upload_files_from_form(form) -> List[UploadFile]:
    """Accept one or many multipart parts named ``files`` (FastAPI List[UploadFile] breaks for a single file)."""
    uploads: List[UploadFile] = []
    for item in form.getlist("files"):
        name = getattr(item, "filename", None)
        if name:
            uploads.append(item)  # type: ignore[arg-type]
    return uploads


@router.get("/chat/categories")
async def ai_chat_categories(
    scope: ExpenseScope = Depends(get_expense_scope),
):
    """Category hierarchy for manual expense chat (same payload as GET /categories/manual)."""
    from app.utils.category_hashtags import get_manual_categories_payload
    from app.utils.payment_modes import list_payment_modes

    payload = get_manual_categories_payload()
    pm = list_payment_modes()
    payload["payment_modes"] = pm["payment_modes"]
    payload["default_payment_mode"] = pm["default"]
    return payload


@router.get("/chat/welcome", response_model=ChatResponse)
async def ai_chat_welcome(
    session_id: str = Query(..., min_length=8, max_length=64),
    scope: ExpenseScope = Depends(get_expense_scope),
    db: Session = Depends(get_db),
    orchestrator: AIOrchestrator = Depends(get_ai_orchestrator),
):
    """Fixed opening message when the user opens a chat session."""
    _guard_session(db, scope, session_id)
    user = _user(db, scope)
    ctx = _ctx(scope, session_id)
    result = await orchestrator.ensure_session_welcome(ctx, user=user)
    return _build_chat_response(result)


@router.post("/chat", response_model=ChatResponse)
async def ai_chat(
    body: ChatRequest,
    scope: ExpenseScope = Depends(get_expense_scope),
    db: Session = Depends(get_db),
    orchestrator: AIOrchestrator = Depends(get_ai_orchestrator),
):
    _guard_session(db, scope, body.session_id)
    user = _user(db, scope)
    ctx = _ctx(scope, body.session_id)
    result = await orchestrator.handle_user_message(
        ctx, body.message, user=user
    )
    return _build_chat_response(
        result,
        expense_previews=result.get("expense_previews"),
        ui_actions=result.get("ui_actions"),
        attachments_enabled=result.get("attachments_enabled"),
        category_picker=result.get("category_picker"),
    )


@router.post("/chat/upload", response_model=ChatResponse)
async def ai_chat_with_attachments(
    request: Request,
    scope: ExpenseScope = Depends(get_expense_scope),
    db: Session = Depends(get_db),
    orchestrator: AIOrchestrator = Depends(get_ai_orchestrator),
    memory: MemoryService = Depends(get_ai_memory_service),
):
    """
    Chat with images and/or PDFs (multipart), similar to ChatGPT attachments.

    Files are sent to the vision LLM for reading; structured fields are extracted
    via LLM vision scanning and saved as draft expenses when possible.
    """
    form = await request.form()
    session_id = str(form.get("session_id") or "").strip()
    if len(session_id) < 8 or len(session_id) > 64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="session_id must be between 8 and 64 characters",
        )
    _guard_session(db, scope, session_id)
    message = str(form.get("message") or "")
    uploads = _upload_files_from_form(form)
    if not uploads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one file (image or PDF), or use POST /ai/chat with JSON.",
        )

    user = _user(db, scope)
    ctx = _ctx(scope, session_id)
    file_infos = await process_multiple_files(uploads)
    if not file_infos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No readable files were uploaded",
        )

    bundle = build_chat_attachment_bundle_from_file_infos(
        message=message,
        file_infos=file_infos,
        max_bytes_per_file=settings.max_upload_size,
    )

    intent_message = bundle.intent_message
    persist_message = bundle.persist_message
    llm_user_content: Optional[object] = bundle.llm_user_content
    scan_tool_results: Optional[list] = None
    expense_previews: Optional[List[ExpensePreviewCard]] = None
    preview_hint = ""

    workflow_state = await memory.get_workflow_state(ctx)
    merge_into_workflow = bool(
        workflow_state is not None
        and (
            workflow_state.slots.get("creation_mode") == "manual"
            or workflow_state.slots.get("_awaiting_attachment")
        )
    )

    if merge_into_workflow:
        try:
            updated_state, preview, preview_hint, category_picker, upload_actions = (
                attach_receipt_to_manual_workflow(
                    db, user, workflow_state, file_infos
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        await memory.set_workflow_state(ctx, updated_state)
        sm = ConversationStateMachine()
        await memory.set_draft_expense(ctx, sm.state_to_draft(updated_state))
        await memory.set_pending_intent(
            ctx,
            PendingIntent(
                intent_type="expense_create",
                parameters={
                    **updated_state.slots,
                    "fields_pending": list(updated_state.pending_slots),
                    "session_id": session_id,
                },
            ),
        )
        user_persist = message.strip() or "Bill attached"
        await orchestrator.store_memory(
            ctx,
            ConversationMessageCreate(role=ConversationRole.USER, content=user_persist),
        )
        assistant_msg = await orchestrator.store_memory(
            ctx,
            ConversationMessageCreate(role=ConversationRole.ASSISTANT, content=preview_hint),
        )
        card_actions = list(upload_actions) if upload_actions else []
        if preview and not updated_state.pending_slots:
            card_actions = list(preview.actions)
        return _build_chat_response(
            {
                "message": assistant_msg,
                "session_id": session_id,
            },
            expense_previews=[preview] if preview else None,
            ui_actions=card_actions or None,
            category_picker=category_picker,
        )

    scan = await run_blocking(
        run_chat_receipt_scans,
        db,
        user,
        file_infos,
        user_message=message,
    )
    for draft in scan.draft_contexts:
        await memory.set_draft_expense(ctx, draft)
    expense_previews = scan.expense_previews or None
    preview_hint = scan.assistant_hint
    if scan.results:
        await memory.clear_workflow_state(ctx)
        await memory.clear_pending_intent(ctx)
        user_persist = message.strip() or "Bill attached"
        await orchestrator.store_memory(
            ctx,
            ConversationMessageCreate(role=ConversationRole.USER, content=user_persist),
        )
        assistant_msg = await orchestrator.store_memory(
            ctx,
            ConversationMessageCreate(
                role=ConversationRole.ASSISTANT,
                content=_GOT_IT_AFTER_ATTACHMENT,
            ),
        )
        card_actions: List[ChatUIAction] = []
        if expense_previews:
            for card in expense_previews:
                card_actions.extend(card.actions)
        scan_tool_results = [
            {
                "tool": "receipt_vision_scan",
                "success": True,
                "data": r.model_dump(mode="json"),
            }
            for r in scan.results
        ]
        return _build_chat_response(
            {
                "message": assistant_msg,
                "session_id": session_id,
                "tool_results": scan_tool_results,
            },
            expense_previews=expense_previews,
            ui_actions=card_actions or None,
        )
    elif scan.errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="; ".join(scan.errors),
        )

    if len(persist_message) > 32000:
        persist_message = persist_message[:31900] + "\n…[truncated]"

    skip_workflow = bool(scan_tool_results)

    result = await orchestrator.handle_user_message(
        ctx,
        intent_message,
        user=user,
        persist_message=persist_message,
        llm_user_content=llm_user_content,
        skip_active_workflow=skip_workflow,
    )
    if scan_tool_results:
        existing = list(result.get("tool_results") or [])
        result["tool_results"] = existing + scan_tool_results

    if preview_hint and expense_previews:
        msg = result.get("message")
        if isinstance(msg, ConversationMessageOut):
            msg.content = preview_hint
        elif isinstance(msg, dict):
            msg["content"] = preview_hint
        result["message"] = msg

    card_actions: List[ChatUIAction] = []
    if expense_previews:
        for card in expense_previews:
            card_actions.extend(card.actions)

    workflow_actions = result.get("ui_actions") or []
    merged_previews = expense_previews or result.get("expense_previews")

    return _build_chat_response(
        result,
        expense_previews=merged_previews,
        ui_actions=card_actions or workflow_actions or None,
    )


@router.post("/chat/end", status_code=status.HTTP_204_NO_CONTENT)
async def ai_chat_end(
    session_id: str = Query(..., min_length=8, max_length=64),
    scope: ExpenseScope = Depends(get_expense_scope),
    db: Session = Depends(get_db),
    orchestrator: AIOrchestrator = Depends(get_ai_orchestrator),
):
    """End a chat session — clears workflow/draft session memory for this session_id."""
    _guard_session(db, scope, session_id)
    user = _user(db, scope)
    await orchestrator.end_session(_ctx(scope, session_id), user=user)


@router.get("/chat/sessions")
async def list_chat_sessions(
    limit: int = Query(30, ge=1, le=100),
    scope: ExpenseScope = Depends(get_expense_scope),
    db: Session = Depends(get_db),
):
    """List persisted chat sessions for the user (messages in ai_conversations)."""
    tenant_id = scope.company_id
    user_id = scope.user_id
    rows = (
        db.query(
            AIConversation.session_id,
            func.max(AIConversation.created_at).label("last_at"),
            func.count(AIConversation.id).label("msg_count"),
        )
        .filter(
            AIConversation.tenant_id == tenant_id,
            AIConversation.user_id == user_id,
        )
        .group_by(AIConversation.session_id)
        .order_by(desc("last_at"))
        .limit(limit)
        .all()
    )
    session_ids = [r.session_id for r in rows]
    meta = {}
    if session_ids:
        for s in (
            db.query(AIChatSession)
            .filter(
                AIChatSession.tenant_id == tenant_id,
                AIChatSession.user_id == user_id,
                AIChatSession.session_id.in_(session_ids),
            )
            .all()
        ):
            meta[s.session_id] = s
    out = []
    for r in rows:
        m = meta.get(r.session_id)
        out.append(
            {
                "session_id": r.session_id,
                "company_id": tenant_id,
                "user_id": user_id,
                "title": (m.title if m else None) or "Expense chat",
                "message_count": int(r.msg_count),
                "last_message_at": r.last_at.isoformat() if r.last_at else None,
                "is_active": m.is_active if m else True,
            }
        )
    return {
        "company_id": tenant_id,
        "user_id": user_id,
        "sessions": out,
    }


@router.get("/chat/sessions/{session_id}/messages")
async def get_chat_session_messages(
    session_id: str,
    limit: int = Query(50, ge=1, le=200),
    scope: ExpenseScope = Depends(get_expense_scope),
    db: Session = Depends(get_db),
):
    _guard_session(db, scope, session_id)
    tenant_id = scope.company_id
    msgs = (
        db.query(AIConversation)
        .filter(
            AIConversation.tenant_id == tenant_id,
            AIConversation.user_id == scope.user_id,
            AIConversation.session_id == session_id,
        )
        .order_by(AIConversation.created_at)
        .limit(limit)
        .all()
    )
    return {
        "session_id": session_id,
        "company_id": tenant_id,
        "user_id": scope.user_id,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@router.get("/dead-letter")
async def list_dead_letter_jobs(
    limit: int = Query(50, ge=1, le=200),
    scope: ExpenseScope = Depends(get_expense_scope),
    dlq: DeadLetterQueueService = Depends(get_dead_letter_service),
):
    """Retry visibility for failed approvals, reimbursements, and submits."""
    rows = dlq.list_failed(
        tenant_id=scope.company_id, user_id=scope.user_id, limit=limit
    )
    return [
        {
            "id": r.id,
            "job_type": r.job_type,
            "status": r.status,
            "error_message": r.error_message,
            "retry_count": r.retry_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "payload": r.payload,
        }
        for r in rows
    ]
