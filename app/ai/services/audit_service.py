"""Audit logging for prompts, tool calls, responses — sanitized, with trace IDs."""
import logging
from typing import Any, Dict, Optional

from app.ai.memory.repository import AIRepository
from app.ai.models.entities import ActionType
from app.ai.observability import get_trace_context
from app.ai.sanitization import sanitize_prompt, sanitize_response
from app.ai.schemas.audit import AuditLogCreate, TokenUsage
from app.ai.schemas.common import TenantUserContext
from app.ai.security import sanitize_audit_payload

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(self, repository: AIRepository):
        self._repo = repository

    def _trace_fields(self) -> Dict[str, Optional[str]]:
        trace = get_trace_context()
        if not trace:
            return {"request_id": None, "trace_id": None}
        return {"request_id": trace.request_id, "trace_id": trace.trace_id}

    def _log_extra(self, ctx: TenantUserContext, **kwargs: Any) -> Dict[str, Any]:
        extra = {"tenant_id": ctx.tenant_id, "user_id": ctx.user_id, **self._trace_fields()}
        extra.update(kwargs)
        return extra

    def log_prompt(
        self,
        ctx: TenantUserContext,
        *,
        session_id: Optional[str],
        model: str,
        messages_summary: Dict[str, Any],
        token_usage: TokenUsage,
        latency_ms: int,
        status: str = "success",
        error_message: Optional[str] = None,
        parent_audit_id: Optional[int] = None,
    ):
        audit = AuditLogCreate(
            action_type=ActionType.PROMPT,
            session_id=session_id,
            model=model,
            payload={"messages_summary": sanitize_prompt(messages_summary)},
            token_usage=token_usage,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            parent_audit_id=parent_audit_id,
            **self._trace_fields(),
        )
        row = self._repo.log_action(ctx, audit)
        logger.info("ai.audit.prompt", extra=self._log_extra(ctx, action_id=row.id))
        return row

    def log_tool_call(
        self,
        ctx: TenantUserContext,
        *,
        session_id: Optional[str],
        tool_name: str,
        arguments: Dict[str, Any],
        latency_ms: int = 0,
        status: str = "success",
        error_message: Optional[str] = None,
        parent_audit_id: Optional[int] = None,
    ):
        audit = AuditLogCreate(
            action_type=ActionType.TOOL_CALL,
            session_id=session_id,
            tool_name=tool_name,
            payload=sanitize_audit_payload({"arguments": sanitize_prompt(arguments)}),
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            parent_audit_id=parent_audit_id,
            **self._trace_fields(),
        )
        row = self._repo.log_action(ctx, audit)
        logger.info("ai.audit.tool_call", extra=self._log_extra(ctx, tool_name=tool_name, action_id=row.id))
        return row

    def log_response(
        self,
        ctx: TenantUserContext,
        *,
        session_id: Optional[str],
        model: str,
        response_preview: str,
        token_usage: TokenUsage,
        latency_ms: int,
        status: str = "success",
        error_message: Optional[str] = None,
        parent_audit_id: Optional[int] = None,
    ):
        safe_preview = sanitize_response(response_preview)
        if not isinstance(safe_preview, str):
            safe_preview = response_preview[:500]

        audit = AuditLogCreate(
            action_type=ActionType.RESPONSE,
            session_id=session_id,
            model=model,
            payload={"response_preview": safe_preview[:500]},
            token_usage=token_usage,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            parent_audit_id=parent_audit_id,
            **self._trace_fields(),
        )
        row = self._repo.log_action(ctx, audit)
        logger.info("ai.audit.response", extra=self._log_extra(ctx, action_id=row.id))
        return row

    def log_summary(
        self,
        ctx: TenantUserContext,
        *,
        session_id: str,
        model: str,
        token_usage: TokenUsage,
        latency_ms: int,
        parent_audit_id: Optional[int] = None,
    ):
        audit = AuditLogCreate(
            action_type=ActionType.SUMMARY,
            session_id=session_id,
            model=model,
            payload={},
            token_usage=token_usage,
            latency_ms=latency_ms,
            parent_audit_id=parent_audit_id,
            **self._trace_fields(),
        )
        return self._repo.log_action(ctx, audit)
