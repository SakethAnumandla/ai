"""Memory governance APIs — explainability, confidence, audit, policy, anomalies."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.ai.memory.anomaly import MemoryAnomalyDetector
from app.ai.memory.audit import MemoryAuditService
from app.ai.memory.explainability import MemoryExplainabilityService
from app.ai.memory.policy import MemoryPolicyService
from app.ai.dependencies import get_ai_repository
from app.ai.memory.repository import AIRepository
from app.ai.schemas.common import TenantUserContext
from app.ai.schemas.memory_governance import (
    MemoryAnomaliesResponse,
    MemoryAuditListResponse,
    MemoryAuditEventOut,
    MemoryConfidenceResponse,
    MemoryExplanationsResponse,
    TenantMemoryPolicyOut,
    TenantMemoryPolicyUpdate,
)
from app.ai.security import resolve_tenant_id
from app.database import get_db
from app.dependencies import get_current_admin_user, get_current_user
from app.models import User

router = APIRouter(prefix="/ai/memory", tags=["ai-memory"])


def _target_context(
    current_user: User,
    *,
    user_id: Optional[int] = None,
    db: Session = None,
    admin: bool = False,
) -> TenantUserContext:
    tenant_id = resolve_tenant_id(current_user)
    target_user_id = current_user.id
    if user_id is not None and user_id != current_user.id:
        if not admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required to view another user's memory",
            )
        if db is not None:
            other = db.query(User).filter(User.id == user_id).first()
            if not other:
                raise HTTPException(status_code=404, detail="User not found")
        target_user_id = user_id
    return TenantUserContext(tenant_id=tenant_id, user_id=target_user_id)


@router.get("/explanations", response_model=MemoryExplanationsResponse)
def get_memory_explanations(
    user_id: Optional[int] = Query(None, description="Admin: inspect another user"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    repo: AIRepository = Depends(get_ai_repository),
):
    """
    Explain why the copilot suggests vendors, payment methods, and categories.
    Useful for debugging, trust, and enterprise admin visibility.
    """
    ctx = _target_context(user, user_id=user_id, db=db, admin=user.is_admin)
    svc = MemoryExplainabilityService(repo, MemoryPolicyService(db))
    return svc.get_explanations(ctx)


@router.get("/confidence", response_model=MemoryConfidenceResponse)
def get_memory_confidence(
    user_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    repo: AIRepository = Depends(get_ai_repository),
):
    """Expose confidence scores and candidate breakdown for admin calibration."""
    ctx = _target_context(user, user_id=user_id, db=db, admin=user.is_admin)
    svc = MemoryExplainabilityService(repo, MemoryPolicyService(db))
    return svc.get_confidence_report(ctx)


@router.get("/audit", response_model=MemoryAuditListResponse)
def list_memory_audit(
    user_id: Optional[int] = Query(None),
    memory_key: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    repo: AIRepository = Depends(get_ai_repository),
):
    """Why did a preference change? Evidence, timestamps, and workflow sources."""
    ctx = _target_context(user, user_id=user_id, db=db, admin=user.is_admin)
    audit = MemoryAuditService(db)
    rows, total = audit.list_events(
        ctx, memory_key=memory_key, change_type=change_type, limit=limit, offset=offset
    )
    return MemoryAuditListResponse(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        total=total,
        events=[
            MemoryAuditEventOut(
                id=r.id,
                memory_key=r.memory_key,
                change_type=r.change_type,
                source=r.source,
                confidence_before=r.confidence_before,
                confidence_after=r.confidence_after,
                evidence=r.evidence or {},
                before_snapshot=r.before_snapshot or {},
                after_snapshot=r.after_snapshot or {},
                created_at=r.created_at,
            )
            for r in rows
        ],
    )


@router.get("/policy", response_model=TenantMemoryPolicyOut)
def get_memory_policy(
    user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """Tenant memory sandbox policy (admin)."""
    tenant_id = resolve_tenant_id(user)
    policy = MemoryPolicyService(db)
    row = policy.get_or_create_row(tenant_id)
    return TenantMemoryPolicyOut(
        tenant_id=tenant_id,
        allow_preference_learning=row.allow_preference_learning,
        allow_behavioral_memory=row.allow_behavioral_memory,
        allow_long_term_storage=row.allow_long_term_storage,
        allow_entity_graph=row.allow_entity_graph,
        allow_anomaly_detection=row.allow_anomaly_detection,
        updated_at=row.updated_at,
    )


@router.put("/policy", response_model=TenantMemoryPolicyOut)
def update_memory_policy(
    body: TenantMemoryPolicyUpdate,
    user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """
    Configure tenant memory sandbox.
    Disable preference learning, behavioral memory, or long-term storage per enterprise policy.
    """
    tenant_id = resolve_tenant_id(user)
    policy = MemoryPolicyService(db)
    row = policy.update_policy(
        tenant_id,
        allow_preference_learning=body.allow_preference_learning,
        allow_behavioral_memory=body.allow_behavioral_memory,
        allow_long_term_storage=body.allow_long_term_storage,
        allow_entity_graph=body.allow_entity_graph,
        allow_anomaly_detection=body.allow_anomaly_detection,
    )
    return TenantMemoryPolicyOut(
        tenant_id=tenant_id,
        allow_preference_learning=row.allow_preference_learning,
        allow_behavioral_memory=row.allow_behavioral_memory,
        allow_long_term_storage=row.allow_long_term_storage,
        allow_entity_graph=row.allow_entity_graph,
        allow_anomaly_detection=row.allow_anomaly_detection,
        updated_at=row.updated_at,
    )


@router.get("/anomalies", response_model=MemoryAnomaliesResponse)
def get_memory_anomalies(
    user_id: Optional[int] = Query(None),
    lookback_days: int = Query(90, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Behavioral anomaly signals: payment method shifts, new vendor clusters,
  elevated submission activity. Advanced fraud/risk hook.
    """
    ctx = _target_context(user, user_id=user_id, db=db, admin=user.is_admin)
    detector = MemoryAnomalyDetector(db, MemoryPolicyService(db))
    return detector.detect(ctx, lookback_days=lookback_days)
