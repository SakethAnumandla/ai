"""Schemas for memory conflict resolution, explanations, and workflow recovery."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowRecoveryScenario(str, Enum):
    NONE = "none"
    STALE_SLOT_FILLING = "stale_slot_filling"
    INTERRUPTED_SUBMIT = "interrupted_submit"
    EXPIRED_CONFIRMATION = "expired_confirmation"
    AMBIGUOUS_DRAFT = "ambiguous_draft"


@dataclass
class MemoryExplanation:
    """Human-readable rationale for a memory-driven suggestion."""

    text: str
    field: str
    confidence: float = 0.0
    evidence_count: int = 0
    category: Optional[str] = None
    superseded: Optional[str] = None

    def format_user_facing(self) -> str:
        return self.text


@dataclass
class PreferenceSuggestion:
    """Payment/vendor suggestion with transparency metadata."""

    prompt: str
    explanation: Optional[MemoryExplanation] = None
    value: Optional[str] = None
    confidence: float = 0.0


@dataclass
class ConflictResolution:
    """Result of resolving competing preference signals."""

    primary_value: str
    primary_confidence: float
    evolved: bool = False
    decayed_values: List[str] = field(default_factory=list)
    explanation: Optional[str] = None


@dataclass
class WorkflowRecoveryAssessment:
    scenario: WorkflowRecoveryScenario = WorkflowRecoveryScenario.NONE
    safe_prompt: Optional[str] = None
    options: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    block_blind_resume: bool = False
