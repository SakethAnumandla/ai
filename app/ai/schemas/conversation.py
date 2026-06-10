from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.ai.models.entities import ConversationRole


class ConversationMessageCreate(BaseModel):
    role: ConversationRole
    content: str = Field(..., min_length=1, max_length=32000)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    token_count: int = Field(default=0, ge=0)

    @field_validator("content")
    @classmethod
    def strip_content(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("content cannot be empty")
        return stripped


class ConversationMessageOut(BaseModel):
    id: int
    role: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    token_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RecentContextOut(BaseModel):
    session_id: str
    messages: List[ConversationMessageOut]
    summary: Optional[str] = None
    compressed: bool = False
