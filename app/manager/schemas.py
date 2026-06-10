"""Phase 5 — manager copilot schemas."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class BulkApprovalFilters(BaseModel):
    """Schema-bound filters — no free-form GPT criteria."""

    main_category: Optional[str] = Field(
        None,
        description="travel, food, bills, etc.",
    )
    max_amount: Optional[float] = Field(None, ge=0)
    min_amount: Optional[float] = Field(None, ge=0)
    department: Optional[str] = None
    max_risk_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    flagged_only: bool = False
    vendor_name: Optional[str] = None


class RiskAssessment(BaseModel):
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_flags: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class RiskScoreBreakdown(BaseModel):
    risk_score: float
    risk_flags: List[str] = Field(default_factory=list)
    contributions: Dict[str, float] = Field(default_factory=dict)
    explanations: List[str] = Field(default_factory=list)
    summary: str = ""
    grounded_facts: Dict[str, Any] = Field(default_factory=dict)


class ApprovalCandidate(BaseModel):
    approval_id: int
    claim_id: int
    claim_number: str
    bill_name: str
    bill_amount: float
    vendor_name: Optional[str] = None
    main_category: Optional[str] = None
    department: Optional[str] = None
    submitter_name: Optional[str] = None
    risk: RiskAssessment
    policy_flags: List[str] = Field(default_factory=list)


class PrioritizedCandidate(ApprovalCandidate):
    priority_score: float = 0.0
    priority_rank: Optional[int] = None
    urgency_reasons: List[str] = Field(default_factory=list)
    hours_waiting: float = 0.0


class BulkApprovalPreview(BaseModel):
    candidates: List[ApprovalCandidate]
    total_amount: float
    count: int
    flagged_count: int
    high_risk_count: int
    summary_text: str
    approval_ids: List[int] = Field(default_factory=list)
    export: Optional[Dict[str, Any]] = None
    simulation: Optional[Dict[str, Any]] = None


class SimulationWarning(BaseModel):
    severity: str = "info"
    code: str
    message: str
    department: Optional[str] = None
    category: Optional[str] = None
    claim_id: Optional[int] = None
    projected_spend: Optional[float] = None
    budget_limit: Optional[float] = None


class SimulationResult(BaseModel):
    action: str
    candidate_count: int
    total_amount: float
    warnings: List[SimulationWarning] = Field(default_factory=list)
    would_exceed_budget: bool = False
    summary_text: str
    candidates: List[Dict[str, Any]] = Field(default_factory=list)


class BehavioralRiskAssessment(BaseModel):
    manager_id: int
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_flags: List[str] = Field(default_factory=list)
    explanations: List[str] = Field(default_factory=list)
    summary: str = ""
    lookback_days: int = 30
    sample_size: int = 0


class SLABreachPrediction(BaseModel):
    approval_id: int
    claim_id: int
    claim_number: str
    breach_probability: float = Field(ge=0.0, le=1.0)
    hours_waiting: float = 0.0
    sla_hours: float = 48.0
    expected_breach_at: Optional[datetime] = None
    reasons: List[str] = Field(default_factory=list)


class SpendForecastOut(BaseModel):
    enabled: bool = False
    period: Optional[str] = None
    forecasts: List[Dict[str, Any]] = Field(default_factory=list)
    message: Optional[str] = None


class QueueSummary(BaseModel):
    total_pending: int
    total_value: float
    by_category: Dict[str, int]
    flagged_count: int
    high_risk_count: int
    summary_text: str
    groups: List[Dict[str, Any]] = Field(default_factory=list)


class PolicyExplanation(BaseModel):
    claim_id: int
    claim_number: str
    flagged: bool
    reasons: List[str]
    policy_name: Optional[str] = None
    policy_limit: Optional[float] = None
    grounded_facts: Dict[str, Any] = Field(default_factory=dict)


class EscalationCreate(BaseModel):
    claim_id: int
    approval_id: Optional[int] = None
    reason: str
    target_role: Literal["finance_admin", "super_admin", "audit"] = "finance_admin"


class EscalationOut(BaseModel):
    id: int
    claim_id: int
    status: str
    reason: str
    risk_score: Optional[float] = None
    risk_flags: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
