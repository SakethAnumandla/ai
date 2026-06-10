"""Request/response schemas for expense workflow endpoints."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ExpenseApprovalAction(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    comments: Optional[str] = None
