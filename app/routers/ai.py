"""AI copilot API."""
import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.ai.chat_ui import global_attach_action
from app.ai.chat_attachments import (
    build_chat_attachment_bundle,
    build_chat_attachment_bundle_from_file_infos,
)
from app.ai.conversation.state_machine import merge_ocr_prefill_into_state
from app.ai.dependencies import (
    get_ai_memory_service,
    get_ai_orchestrator,
    get_dead_letter_service,
)
from app.ai.dead_letter.service import DeadLetterQueueService
from app.ai.orchestrator.base import AIOrchestrator
from app.ai.receipt_chat import is_receipt_file, run_chat_receipt_scans
from app.ai.schemas.chat import ChatRequest, ChatResponse
from app.ai.schemas.chat_ui import ChatUIAction, ExpensePreviewCard
from app.ai.schemas.conversation import ConversationMessageOut
from app.ai.security import build_session_context, resolve_tenant_id
from app.ai.services.memory_service import MemoryService
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import AIChatSession, User
from sqlalchemy import desc, func
from app.ai.models.entities import AIConversation
from app.utils.file_upload import process_multiple_files

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


def _build_chat_response(
    result: dict,
    *,
    expense_previews: Optional[List[ExpensePreviewCard]] = None,
    ui_actions: Optional[List[ChatUIAction]] = None,
) -> ChatResponse:
    msg = result["message"]
    actions = list(ui_actions or [])
    if not any(a.action == "attach" for a in actions):
        actions.insert(0, global_attach_action())
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
        attachments_enabled=True,
        expense_previews=expense_previews,
        ui_actions=actions,
    )


def _upload_files_from_form(form) -> List[UploadFile]:
    """Accept one or many multipart parts named ``files`` (FastAPI List[UploadFile] breaks for a single file)."""
    uploads: List[UploadFile] = []
    for item in form.getlist("files"):
        name = getattr(item, "filename", None)
        if name:
            uploads.append(item)  # type: ignore[arg-type]
    return uploads


@router.get("/chat/welcome", response_model=ChatResponse)
async def ai_chat_welcome(
    session_id: str = Query(..., min_length=8, max_length=64),
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_ai_orchestrator),
):
    """Fixed opening message when the user opens a chat session."""
    ctx = build_session_context(user, session_id)
    result = await orchestrator.ensure_session_welcome(ctx, user=user)
    return _build_chat_response(result)


@router.post("/chat", response_model=ChatResponse)
async def ai_chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_ai_orchestrator),
):
    ctx = build_session_context(user, body.session_id)
    result = await orchestrator.handle_user_message(
        ctx, body.message, user=user
    )
    return _build_chat_response(result)


@router.post("/chat/upload", response_model=ChatResponse)
async def ai_chat_with_attachments(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    orchestrator: AIOrchestrator = Depends(get_ai_orchestrator),
    memory: MemoryService = Depends(get_ai_memory_service),
):
    """
    Chat with optional images and/or PDFs (multipart), similar to ChatGPT attachments.

    Receipt images/PDFs (JPEG/PNG/WebP/PDF) are analyzed with OCR, saved as draft expenses,
    and summarized for the copilot. Other file types (e.g. GIF) use vision/PDF text extraction.
    """
    form = await request.form()
    session_id = str(form.get("session_id") or "").strip()
    if len(session_id) < 8 or len(session_id) > 64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="session_id must be between 8 and 64 characters",
        )
    message = str(form.get("message") or "")
    uploads = _upload_files_from_form(form)
    if not uploads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one file (image or PDF), or use POST /ai/chat with JSON.",
        )

    ctx = build_session_context(user, session_id)
    file_infos = await process_multiple_files(uploads)
    receipt_infos = [fi for fi in file_infos if is_receipt_file(fi)]
    non_receipt_infos = [fi for fi in file_infos if not is_receipt_file(fi)]

    intent_message = (message or "").strip()
    persist_message = ""
    llm_user_content: Optional[object] = None
    scan_tool_results: Optional[list] = None
    expense_previews: Optional[List[ExpensePreviewCard]] = None
    preview_hint = ""

    workflow_state = await memory.get_workflow_state(ctx)
    merge_into_workflow = bool(
        workflow_state is not None
        and workflow_state.slots.get("creation_mode") == "manual"
    )

    if receipt_infos:
        scan = await asyncio.to_thread(
            run_chat_receipt_scans,
            db,
            user,
            receipt_infos,
            user_message=message,
        )
        for draft in scan.draft_contexts:
            await memory.set_draft_expense(ctx, draft)
        expense_previews = scan.expense_previews or None
        preview_hint = scan.assistant_hint
        intent_message = scan.intent_message
        persist_message = scan.persist_message
        llm_user_content = scan.llm_user_content
        scan_tool_results = [
            {
                "tool": "receipt_ocr_scan",
                "success": True,
                "data": r.model_dump(mode="json"),
            }
            for r in scan.results
        ]
        if scan.errors and not scan.results:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="; ".join(scan.errors),
            )

        if merge_into_workflow and scan.results:
            prefill = scan.results[-1].prefill or {}
            expense_id = scan.results[-1].expense_id
            merged = merge_ocr_prefill_into_state(
                workflow_state,
                prefill,
                expense_id=expense_id,
            )
            await memory.set_workflow_state(ctx, merged)
            if scan.draft_contexts:
                await memory.set_draft_expense(ctx, scan.draft_contexts[-1])
            preview_hint = (
                "I've scanned your receipt and updated the expense details. "
                "Review the preview below, then **Edit** any field or **Submit**."
            )
        elif scan.results:
            # Exit OCR "attach a receipt" wait — draft + preview cards carry state forward.
            await memory.clear_workflow_state(ctx)
            await memory.clear_pending_intent(ctx)

    if non_receipt_infos:
        bundle = build_chat_attachment_bundle_from_file_infos(
            message=intent_message or message,
            file_infos=non_receipt_infos,
            max_bytes_per_file=settings.max_upload_size,
        )
        if receipt_infos:
            persist_message = f"{persist_message}\n{bundle.persist_message}".strip()
            ocr_text = str(llm_user_content)
            extra = (
                bundle.llm_user_content
                if isinstance(bundle.llm_user_content, list)
                else [{"type": "text", "text": str(bundle.llm_user_content)}]
            )
            llm_user_content = [{"type": "text", "text": ocr_text}, *extra[1:]]
        else:
            intent_message = bundle.intent_message
            persist_message = bundle.persist_message
            llm_user_content = bundle.llm_user_content

    if not receipt_infos and not non_receipt_infos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No readable files were uploaded",
        )

    if len(persist_message) > 32000:
        persist_message = persist_message[:31900] + "\n…[truncated]"

    # OCR path skips slot machine unless merging into an active manual workflow.
    skip_workflow = bool(scan_tool_results) and not merge_into_workflow

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

    return _build_chat_response(
        result,
        expense_previews=expense_previews,
        ui_actions=card_actions or None,
    )


@router.post("/chat/end", status_code=status.HTTP_204_NO_CONTENT)
async def ai_chat_end(
    session_id: str = Query(..., min_length=8, max_length=64),
    user: User = Depends(get_current_user),
    orchestrator: AIOrchestrator = Depends(get_ai_orchestrator),
):
    """End a chat session — clears workflow/draft/redis cache for this session_id."""
    ctx = build_session_context(user, session_id)
    await orchestrator.end_session(ctx, user=user)


@router.get("/chat/sessions")
async def list_chat_sessions(
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List persisted chat sessions for the user (messages in ai_conversations)."""
    tenant_id = resolve_tenant_id(user)
    rows = (
        db.query(
            AIConversation.session_id,
            func.max(AIConversation.created_at).label("last_at"),
            func.count(AIConversation.id).label("msg_count"),
        )
        .filter(
            AIConversation.tenant_id == tenant_id,
            AIConversation.user_id == user.id,
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
                AIChatSession.user_id == user.id,
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
                "title": (m.title if m else None) or "Expense chat",
                "message_count": int(r.msg_count),
                "last_message_at": r.last_at.isoformat() if r.last_at else None,
                "is_active": m.is_active if m else True,
            }
        )
    return {"sessions": out}


@router.get("/chat/sessions/{session_id}/messages")
async def get_chat_session_messages(
    session_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant_id = resolve_tenant_id(user)
    msgs = (
        db.query(AIConversation)
        .filter(
            AIConversation.tenant_id == tenant_id,
            AIConversation.user_id == user.id,
            AIConversation.session_id == session_id,
        )
        .order_by(AIConversation.created_at)
        .limit(limit)
        .all()
    )
    return {
        "session_id": session_id,
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
    user: User = Depends(get_current_user),
    dlq: DeadLetterQueueService = Depends(get_dead_letter_service),
):
    """Retry visibility for failed approvals, reimbursements, and submits."""
    tenant_id = resolve_tenant_id(user)
    rows = dlq.list_failed(tenant_id=tenant_id, user_id=user.id, limit=limit)
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
