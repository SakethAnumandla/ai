"""Phase 3 workflow and reference resolution schemas."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkflowScope(str, Enum):
    EXPENSE = "expense"
    APPROVAL = "approval"
    REIMBURSEMENT = "reimbursement"
    ANALYTICS = "analytics"
    GENERAL = "general"


class WorkflowType(str, Enum):
    EXPENSE_CREATE = "expense_create"
    EXPENSE_CONTINUE = "expense_continue"
    EXPENSE_SUBMIT = "expense_submit"
    EXPENSE_DELETE = "expense_delete"
    EXPENSE_UPDATE = "expense_update"
    APPROVAL_REVIEW = "approval_review"


class ConversationWorkflowState(BaseModel):
    """Multi-turn slot-filling state (Redis-backed)."""

    workflow_type: WorkflowType
    scope: WorkflowScope = WorkflowScope.EXPENSE
    slots: Dict[str, Any] = Field(default_factory=dict)
    pending_slots: List[str] = Field(default_factory=list)
    expense_id: Optional[int] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    session_id: Optional[str] = None

    def next_pending(self) -> Optional[str]:
        return self.pending_slots[0] if self.pending_slots else None

    def fill_slot(self, name: str, value: Any) -> None:
        self.slots[name] = value
        if name in self.pending_slots:
            self.pending_slots.remove(name)
        self.updated_at = datetime.utcnow()


class ResolvedReferences(BaseModel):
    """Output of ReferenceResolver."""

    bill_amount: Optional[float] = None
    vendor_name: Optional[str] = None
    payment_method: Optional[str] = None
    main_category: Optional[str] = None
    sub_category: Optional[str] = None
    expense_id: Optional[int] = None
    bill_name: Optional[str] = None
    description: Optional[str] = None
    bill_date: Optional[str] = None
    temporal_label: Optional[str] = None
    source_expense_id: Optional[int] = None
    notes: List[str] = Field(default_factory=list)
    matched_phrases: List[str] = Field(default_factory=list)

    def apply_to_slots(self, slots: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(slots)
        for key in (
            "bill_amount", "vendor_name", "payment_method", "main_category",
            "sub_category", "expense_id", "bill_name", "description", "bill_date",
        ):
            val = getattr(self, key)
            if val is not None and out.get(key) is None:
                out[key] = val
        return out


class WorkflowSnapshot(BaseModel):
    """Active ERP + conversational workflows for proactive context."""

    draft_count: int = 0
    pending_approval_count: int = 0
    latest_draft_id: Optional[int] = None
    latest_draft_label: Optional[str] = None
    incomplete_fields: List[str] = Field(default_factory=list)
    scope: WorkflowScope = WorkflowScope.GENERAL
    summary_lines: List[str] = Field(default_factory=list)


class StateMachineResult(BaseModel):
    handled: bool = False
    assistant_message: Optional[str] = None
    ready_tool_name: Optional[str] = None
    ready_arguments: Dict[str, Any] = Field(default_factory=dict)
    updated_state: Optional[ConversationWorkflowState] = None
    clear_state: bool = False
    ui_actions: Optional[List[Any]] = None
    sync_draft: bool = False


class ContinuityResult(BaseModel):
    handled: bool = False
    message: Optional[str] = None
    resumed_state: Optional[ConversationWorkflowState] = None
