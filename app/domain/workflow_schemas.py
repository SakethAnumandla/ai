"""Request/response schemas for expense workflow endpoints."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ExpenseApprovalAction(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    comments: Optional[str] = Field(
        None,
        description="Approver remarks (required for approve and reject)",
    )
    remarks: Optional[str] = Field(
        None,
        description="Alias for comments — approver remarks stored on the bill",
    )

    def resolved_remarks(self) -> Optional[str]:
        raw = self.remarks if self.remarks is not None else self.comments
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None
