"""Phase 4 — voice and receipt intelligence schemas."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    VOICE_TRANSCRIBE = "voice_transcribe"
    VOICE_CHAT = "voice_chat"
    RECEIPT_OCR = "receipt_ocr"
    FINANCE_REPORT = "finance_report"


class FieldConfidence(BaseModel):
    field: str
    value: Any = None
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool = False
    source: str = "ocr"
    confidence_reason: Optional[str] = None


class ReceiptEntities(BaseModel):
    merchant: Optional[str] = None
    merchant_normalized: Optional[str] = None
    vendor_gst: Optional[str] = None
    invoice_date: Optional[datetime] = None
    invoice_id: Optional[str] = None
    subtotal: Optional[float] = None
    total: Optional[float] = None
    tax: Optional[float] = None
    currency: str = "INR"
    payment_method: Optional[str] = None
    main_category: Optional[str] = None
    sub_category: Optional[str] = None
    field_confidence: Dict[str, FieldConfidence] = Field(default_factory=dict)


class FraudCheckResult(BaseModel):
    check: str
    passed: bool
    severity: str = "info"
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class ReceiptAutofillSuggestion(BaseModel):
    bill_name: Optional[str] = None
    bill_amount: Optional[float] = None
    vendor_name: Optional[str] = None
    main_category: Optional[str] = None
    payment_method: Optional[str] = None
    explanation: Optional[str] = None
    memory_hints: List[str] = Field(default_factory=list)
    fields_needing_clarification: List[str] = Field(default_factory=list)


class ReceiptReviewConfirmRequest(BaseModel):
    review_token: str
    corrections: Optional[Dict[str, Any]] = None


class ReceiptPipelineResult(BaseModel):
    ocr_explanations: List[str] = Field(default_factory=list)
    expense_id: Optional[int] = None
    ocr_bill_id: Optional[int] = None
    entities: ReceiptEntities
    autofill: ReceiptAutofillSuggestion
    fraud_checks: List[FraudCheckResult] = Field(default_factory=list)
    prefill: Dict[str, Any] = Field(default_factory=dict)
    is_duplicate: bool = False
    overall_confidence: float = 0.0
    requires_confirmation: bool = True
    requires_human_review: bool = False
    review_status: str = "pending"
    review_token: Optional[str] = None
    review_payload: Optional[Dict[str, Any]] = None
    ocr_provider: Optional[str] = None
    pdf_page_count: Optional[int] = None
    assistant_message: Optional[str] = None


class ProcessingJobOut(BaseModel):
    id: int
    job_type: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    progress: Optional[str] = None

    model_config = {"from_attributes": True}


class VoiceTranscriptionResult(BaseModel):
    transcript: str
    language: Optional[str] = None
    duration_seconds: Optional[float] = None
    confidence: float = 0.0


class VoiceChatResult(BaseModel):
    transcript: str
    language: Optional[str] = None
    session_id: str
    assistant_message: str
    chat_response: Optional[Dict[str, Any]] = None
