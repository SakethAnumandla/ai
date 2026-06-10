"""Standard tool result envelope — all tools must return this format."""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    success: bool
    message: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    tool: Optional[str] = None
    error: Optional[str] = None
    audit_id: Optional[str] = None
    requires_confirmation: bool = False
    confirmation_token: Optional[str] = None
    safety_flags: list[str] = Field(default_factory=list)

    @classmethod
    def pending_confirmation(
        cls,
        message: str,
        *,
        confirmation_token: str,
        data: Optional[Dict[str, Any]] = None,
        safety_flags: Optional[list[str]] = None,
    ) -> "ToolResult":
        return cls(
            success=False,
            message=message,
            data=data or {},
            error=None,
            requires_confirmation=True,
            confirmation_token=confirmation_token,
            safety_flags=safety_flags or [],
        )

    @classmethod
    def ok(
        cls,
        message: str = "OK",
        *,
        data: Optional[Dict[str, Any]] = None,
        audit_id: Optional[str] = None,
    ) -> "ToolResult":
        return cls(
            success=True,
            message=message,
            data=data or {},
            error=None,
            audit_id=audit_id,
        )

    @classmethod
    def fail(
        cls,
        message: str,
        *,
        error: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        audit_id: Optional[str] = None,
    ) -> "ToolResult":
        return cls(
            success=False,
            message=message,
            data=data or {},
            error=error or message,
            audit_id=audit_id,
        )
