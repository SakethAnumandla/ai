from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from app.ai.models.entities import ActionType


class TokenUsage(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class AuditLogCreate(BaseModel):
    action_type: ActionType
    session_id: Optional[str] = Field(default=None, max_length=64)
    request_id: Optional[str] = Field(default=None, max_length=64)
    trace_id: Optional[str] = Field(default=None, max_length=64)
    parent_audit_id: Optional[int] = None
    tool_name: Optional[str] = Field(default=None, max_length=128)
    model: Optional[str] = Field(default=None, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = Field(default=0, ge=0)
    status: str = Field(default="success", pattern=r"^(success|error|timeout)$")
    error_message: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("payload")
    @classmethod
    def payload_must_be_dict(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("payload must be a dictionary")
        return v


class AuditLogOut(BaseModel):
    id: int
    action_type: str
    session_id: Optional[str]
    tool_name: Optional[str]
    model: Optional[str]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
