"""Security guards: tenant/user isolation and safe payload handling."""
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from app.ai.sanitization import sanitize_prompt
from app.ai.schemas.common import TenantUserContext, SessionContext
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
    return TenantUserContext(tenant_id=resolve_tenant_id(user), user_id=user.id)


def build_session_context(user: User, session_id: str) -> SessionContext:
    base = build_tenant_context(user)
    return SessionContext(
        tenant_id=base.tenant_id,
        user_id=base.user_id,
        session_id=session_id,
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
