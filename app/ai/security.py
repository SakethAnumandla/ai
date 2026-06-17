"""Security guards: tenant/user isolation and safe payload handling."""
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from app.ai.sanitization import sanitize_prompt
from app.ai.schemas.common import TenantUserContext, SessionContext
from app.deps.scope import ExpenseScope
from app.models import User

# Keys that must never be persisted in audit payloads
_SENSITIVE_KEYS = frozenset({
    "api_key", "password", "token", "secret", "authorization",
    "openai_api_key", "hashed_password",
})

# Blocked patterns — no raw prompt execution from untrusted input
_BLOCKED_EXEC_PATTERNS = (
    "eval(", "exec(", "__import__", "os.system", "subprocess",
)


def resolve_tenant_id(user: User) -> int:
    """
    Resolve tenant for isolation. Uses department hash until org/tenant model exists.
    Single-org dev defaults to tenant_id=1 when department is unset.
    """
    if user.department is not None:
        return abs(hash(user.department.value)) % (10**9) or 1
    return 1


def build_tenant_context(user: User) -> TenantUserContext:
    company_id = int(getattr(user, "company_id", None) or resolve_tenant_id(user))
    return TenantUserContext(
        tenant_id=company_id, user_id=user.id, company_id=company_id
    )


def build_session_context(user: User, session_id: str) -> SessionContext:
    base = build_tenant_context(user)
    return SessionContext(
        tenant_id=base.tenant_id,
        user_id=base.user_id,
        company_id=base.scoped_company_id,
        session_id=session_id,
    )


def build_session_context_from_scope(scope: ExpenseScope, session_id: str) -> SessionContext:
    return SessionContext(
        tenant_id=scope.company_id,
        user_id=scope.user_id,
        company_id=scope.company_id,
        session_id=session_id,
    )


def scoped_company_id(
    ctx: SessionContext, user: Optional[User] = None
) -> int:
    """Prefer request/session scope (query param) over the ORM user row."""
    _ = user
    return int(ctx.scoped_company_id)


def tenant_user_from_ctx(ctx: SessionContext) -> TenantUserContext:
    """Tenant + user identity for AI persistence (tenant_id == company_id)."""
    company_id = scoped_company_id(ctx)
    return TenantUserContext(
        tenant_id=company_id,
        user_id=ctx.user_id,
        company_id=company_id,
    )


def assert_chat_session_access(
    db,
    *,
    company_id: int,
    user_id: int,
    session_id: str,
) -> None:
    """
    Reject session_id values that belong to another company or user.

    New session IDs (not yet used) are allowed so clients can generate UUIDs locally.
    """
    from sqlalchemy import or_

    from app.ai.models.entities import AIConversation, AIMemory
    from app.models import AIChatSession

    foreign = or_(
        AIChatSession.tenant_id != company_id,
        AIChatSession.user_id != user_id,
    )
    if (
        db.query(AIChatSession.id)
        .filter(AIChatSession.session_id == session_id, foreign)
        .limit(1)
        .first()
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat session not accessible for this company and user",
        )

    foreign_conv = or_(
        AIConversation.tenant_id != company_id,
        AIConversation.user_id != user_id,
    )
    if (
        db.query(AIConversation.id)
        .filter(AIConversation.session_id == session_id, foreign_conv)
        .limit(1)
        .first()
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat session not accessible for this company and user",
        )

    suffix = f":{session_id}"
    foreign_mem = or_(
        AIMemory.tenant_id != company_id,
        AIMemory.user_id != user_id,
    )
    if (
        db.query(AIMemory.id)
        .filter(AIMemory.memory_key.like(f"%{suffix}"), foreign_mem)
        .limit(1)
        .first()
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat session not accessible for this company and user",
        )


def assert_resource_owner(
    ctx: TenantUserContext,
    *,
    tenant_id: int,
    user_id: int,
) -> None:
    if ctx.tenant_id != tenant_id or ctx.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: resource belongs to another tenant or user",
        )


def sanitize_audit_payload(payload: Dict[str, Any], max_length: int = 8000) -> Dict[str, Any]:
    """Strip secrets and truncate large values for audit storage."""

    def _clean(obj: Any, depth: int = 0) -> Any:
        if depth > 5:
            return "[truncated: depth]"
        if isinstance(obj, dict):
            return {
                k: _clean(v, depth + 1)
                for k, v in obj.items()
                if k.lower() not in _SENSITIVE_KEYS
            }
        if isinstance(obj, list):
            return [_clean(i, depth + 1) for i in obj[:50]]
        if isinstance(obj, str):
            cleaned = sanitize_prompt(obj)
            if not isinstance(cleaned, str):
                cleaned = obj
            if len(cleaned) > max_length:
                return cleaned[:max_length] + "…[truncated]"
            for pattern in _BLOCKED_EXEC_PATTERNS:
                if pattern in cleaned.lower():
                    return "[redacted: blocked pattern]"
            return cleaned
        return obj

    return _clean(payload) or {}


def validate_user_message(content: str) -> str:
    """Reject messages that attempt code execution patterns."""
    lowered = content.lower()
    for pattern in _BLOCKED_EXEC_PATTERNS:
        if pattern in lowered:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message contains disallowed content",
            )
    return content
