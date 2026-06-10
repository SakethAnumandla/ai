"""API schemas for memory explainability, policy, audit, and anomalies."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TenantMemoryPolicyOut(BaseModel):
    tenant_id: int
    allow_preference_learning: bool = True
    allow_behavioral_memory: bool = True
    allow_long_term_storage: bool = True
    allow_entity_graph: bool = True
    allow_anomaly_detection: bool = True
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TenantMemoryPolicyUpdate(BaseModel):
    allow_preference_learning: Optional[bool] = None
    allow_behavioral_memory: Optional[bool] = None
    allow_long_term_storage: Optional[bool] = None
    allow_entity_graph: Optional[bool] = None
    allow_anomaly_detection: Optional[bool] = None


class MemoryExplanationItem(BaseModel):
    field: str
    memory_key: str
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_count: int = 0
    category: Optional[str] = None
    tentative: bool = False
    candidates: Dict[str, Any] = Field(default_factory=dict)


class MemoryExplanationsResponse(BaseModel):
    tenant_id: int
    user_id: int
    explanations: List[MemoryExplanationItem] = Field(default_factory=list)
    policy: TenantMemoryPolicyOut
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ConfidenceCandidateOut(BaseModel):
    value: str
    confidence: float
    weighted_count: float = 0.0
    count: int = 0
    last_used_at: Optional[str] = None


class MemoryConfidenceItem(BaseModel):
    memory_key: str
    memory_type: str
    primary_value: Optional[str] = None
    primary_confidence: float = 0.0
    importance: float = 0.0
    tentative: bool = False
    candidates: List[ConfidenceCandidateOut] = Field(default_factory=list)
    evolved_at: Optional[str] = None


class MemoryConfidenceResponse(BaseModel):
    tenant_id: int
    user_id: int
    items: List[MemoryConfidenceItem] = Field(default_factory=list)
    policy: TenantMemoryPolicyOut


class MemoryAuditEventOut(BaseModel):
    id: int
    memory_key: str
    change_type: str
    source: Optional[str] = None
    confidence_before: Optional[float] = None
    confidence_after: Optional[float] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    before_snapshot: Dict[str, Any] = Field(default_factory=dict)
    after_snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryAuditListResponse(BaseModel):
    tenant_id: int
    user_id: int
    events: List[MemoryAuditEventOut] = Field(default_factory=list)
    total: int = 0


class MemoryAnomalyOut(BaseModel):
    anomaly_type: str
    severity: str
    description: str
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    context: Dict[str, Any] = Field(default_factory=dict)


class MemoryAnomaliesResponse(BaseModel):
    tenant_id: int
    user_id: int
    anomalies: List[MemoryAnomalyOut] = Field(default_factory=list)
    policy: TenantMemoryPolicyOut
