"""SQLAlchemy models for AI persistence layer (PostgreSQL)."""
import enum

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    String,
    Text,
    Float,
    DateTime,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.sql import func

from app.database import Base


class ConversationRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MemoryType(str, enum.Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    CONTEXT = "context"
    WORKFLOW = "workflow"
    GRAPH = "graph"


class ActionType(str, enum.Enum):
    PROMPT = "prompt"
    TOOL_CALL = "tool_call"
    RESPONSE = "response"
    SUMMARY = "summary"


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        Index("ix_ai_conv_tenant_user_session", "tenant_id", "user_id", "session_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIMemory(Base):
    __tablename__ = "ai_memory"
    __table_args__ = (
        Index("ix_ai_mem_tenant_user", "tenant_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    memory_type = Column(String(32), nullable=False)
    memory_key = Column(String(255), nullable=False)
    value = Column(JSON, nullable=False, default=dict)
    importance = Column(Float, default=0.5)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AISummary(Base):
    __tablename__ = "ai_summaries"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(64), nullable=False)
    summary_text = Column(Text, nullable=False)
    token_count_before = Column(Integer, default=0)
    token_count_after = Column(Integer, default=0)
    model = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIModelConfig(Base):
    """Per-tenant model configuration for enterprise admin control."""

    __tablename__ = "ai_model_config"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    model_name = Column(String(64), nullable=False)
    temperature = Column(Float, default=0.2)
    enabled_tools = Column(JSON, default=list)
    max_tokens = Column(Integer, default=4096)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AIIdempotencyRecord(Base):
    """Dedupes mutating AI tool actions (submit, approve, reimburse)."""

    __tablename__ = "ai_idempotency_keys"
    __table_args__ = (
        Index(
            "uq_ai_idempotency_tenant_user_key_action",
            "tenant_id",
            "user_id",
            "idempotency_key",
            "action_type",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    action_type = Column(String(64), nullable=False)
    response_payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), default="completed")
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIConfirmation(Base):
    __tablename__ = "ai_confirmations"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(64), nullable=False)
    confirmation_token = Column(String(64), nullable=False, unique=True, index=True)
    tool_name = Column(String(128), nullable=False)
    arguments = Column(JSON, nullable=False, default=dict)
    summary_message = Column(Text, nullable=False)
    status = Column(String(32), default="pending")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TenantAIUsage(Base):
    __tablename__ = "tenant_ai_usage"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    usage_date = Column(DateTime(timezone=True), nullable=False)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)
    request_count = Column(Integer, default=0)
    tool_invocation_count = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AIToolPermission(Base):
    __tablename__ = "ai_tool_permissions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    role = Column(String(64), nullable=False)
    tool_name = Column(String(128), nullable=False)
    action = Column(String(64), nullable=False, default="execute")
    scope = Column(String(64), nullable=False, default="own")
    allowed = Column(Boolean, default=True)


class AIPromptVersion(Base):
    __tablename__ = "ai_prompt_versions"

    id = Column(Integer, primary_key=True, index=True)
    prompt_key = Column(String(128), nullable=False, unique=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    role_target = Column(String(64), nullable=True)
    content = Column(Text, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AITenantMemoryPolicy(Base):
    """Tenant sandbox: which memory capabilities are allowed."""

    __tablename__ = "ai_tenant_memory_policies"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, unique=True, index=True)
    allow_preference_learning = Column(Boolean, default=True, nullable=False)
    allow_behavioral_memory = Column(Boolean, default=True, nullable=False)
    allow_long_term_storage = Column(Boolean, default=True, nullable=False)
    allow_entity_graph = Column(Boolean, default=True, nullable=False)
    allow_anomaly_detection = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AIMemoryAuditEvent(Base):
    """Audit trail for preference changes and memory governance."""

    __tablename__ = "ai_memory_audit_events"
    __table_args__ = (
        Index("ix_ai_mem_audit_tenant_user_time", "tenant_id", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    memory_key = Column(String(255), nullable=False)
    change_type = Column(String(64), nullable=False)
    source = Column(String(128), nullable=True)
    confidence_before = Column(Float, nullable=True)
    confidence_after = Column(Float, nullable=True)
    before_snapshot = Column(JSON, default=dict)
    after_snapshot = Column(JSON, default=dict)
    evidence = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIJobDeadLetter(Base):
    """Failed reimbursements, approvals, and async tool jobs for retry visibility."""

    __tablename__ = "ai_job_dead_letters"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(64), nullable=True)
    job_type = Column(String(128), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    status = Column(String(32), default="failed")
    retry_count = Column(Integer, default=0)
    trace_id = Column(String(64), nullable=True)
    request_id = Column(String(64), nullable=True)
    last_retry_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIAction(Base):
    __tablename__ = "ai_actions"
    __table_args__ = (
        Index("ix_ai_act_tenant_user", "tenant_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(64), nullable=True)
    request_id = Column(String(64), nullable=True, index=True)
    trace_id = Column(String(64), nullable=True, index=True)
    action_type = Column(String(32), nullable=False)
    tool_name = Column(String(128), nullable=True)
    model = Column(String(64), nullable=True)
    payload = Column(JSON, default=dict)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    status = Column(String(32), default="success")
    error_message = Column(Text, nullable=True)
    parent_audit_id = Column(Integer, ForeignKey("ai_actions.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
