"""Phase 5 manager persistence models."""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON, Index
from sqlalchemy.sql import func

from app.database import Base


class ApprovalEscalation(Base):
    __tablename__ = "approval_escalations"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    approval_id = Column(Integer, ForeignKey("claim_approvals.id", ondelete="SET NULL"), nullable=True)
    escalated_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_role = Column(String(32), nullable=False, default="finance_admin")
    reason = Column(Text, nullable=False)
    risk_score = Column(Float, nullable=True)
    risk_flags = Column(JSON, default=list)
    status = Column(String(32), default="open", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_escalations_tenant_status", "tenant_id", "status"),
    )
