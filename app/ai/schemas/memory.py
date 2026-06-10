from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.ai.models.entities import MemoryType


class MemoryEntryCreate(BaseModel):
    memory_type: MemoryType
    memory_key: str = Field(..., min_length=1, max_length=255)
    value: Dict[str, Any] = Field(default_factory=dict)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    expires_at: Optional[datetime] = None

    @field_validator("memory_key")
    @classmethod
    def normalize_key(cls, v: str) -> str:
        return v.strip().lower()


class MemoryEntryOut(BaseModel):
    id: int
    memory_type: str
    memory_key: str
    value: Dict[str, Any]
    importance: float
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class DraftExpenseContext(BaseModel):
    """Short-term draft expense state stored in Redis."""

    expense_id: Optional[int] = None
    bill_name: Optional[str] = None
    bill_amount: Optional[float] = Field(default=None, ge=0)
    main_category: Optional[str] = None
    sub_category: Optional[str] = None
    vendor_name: Optional[str] = None
    payment_method: Optional[str] = None
    fields_pending: List[str] = Field(default_factory=list)
    source_utterance: Optional[str] = None
    raw_ocr_hints: Dict[str, Any] = Field(default_factory=dict)


class PendingIntent(BaseModel):
    """Pending user intent awaiting confirmation or tool execution."""

    intent_type: str = Field(..., min_length=1, max_length=64)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
