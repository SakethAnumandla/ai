"""Shared typed context objects for AI operations."""
from pydantic import BaseModel, Field, field_validator
import re

_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


class TenantUserContext(BaseModel):
    """Scoped identity for every AI read/write."""

    tenant_id: int = Field(..., ge=1)
    user_id: int = Field(..., ge=1)

    model_config = {"frozen": True}


class SessionContext(TenantUserContext):
    """Session-scoped context extending tenant/user isolation."""

    session_id: str = Field(..., min_length=8, max_length=64)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not _SESSION_ID_PATTERN.match(v):
            raise ValueError("session_id must be 8-64 alphanumeric characters, hyphens, or underscores")
        return v

    model_config = {"frozen": True}
