"""Finance analytics persistence — snapshots, KPI alerts, report access audit."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, JSON, Index
from sqlalchemy.sql import func

from app.database import Base


class AnalyticsSnapshot(Base):
    """Point-in-time analytics for executive / month-end reporting."""

    __tablename__ = "analytics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    snapshot_type = Column(String(64), nullable=False)
    period_label = Column(String(32), nullable=False)
    department = Column(String(32), nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    summary_text = Column(Text, nullable=True)
    immutable = Column(Boolean, default=False, nullable=False)
    is_executive = Column(Boolean, default=False, nullable=False)
    content_hash = Column(String(64), nullable=True)
    frozen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_analytics_snapshots_tenant_type", "tenant_id", "snapshot_type", "created_at"),
    )


class KPIAlert(Base):
    """Finance KPI alerts — budget spike, policy surge, SLA breach."""

    __tablename__ = "kpi_alerts"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    alert_type = Column(String(64), nullable=False)
    severity = Column(String(16), default="medium")
    priority = Column(String(16), default="medium", index=True)
    correlation_id = Column(String(64), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(JSON, default=dict)
    status = Column(String(16), default="open")
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_kpi_alerts_tenant_status", "tenant_id", "status", "created_at"),
        Index("ix_kpi_alerts_tenant_priority", "tenant_id", "priority", "status"),
    )


class FinanceReportAccessAudit(Base):
    """Who downloaded executive / finance async reports."""

    __tablename__ = "finance_report_access_audits"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_id = Column(Integer, nullable=False, index=True)
    report_type = Column(String(64), nullable=False)
    report_version = Column(String(64), nullable=True)
    file_format = Column(String(16), nullable=False)
    file_path = Column(Text, nullable=False)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    accessed_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_finance_report_audit_tenant_time", "tenant_id", "accessed_at"),
    )
