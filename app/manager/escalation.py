"""Escalation workflows — manager → finance → audit."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.manager.risk_engine import ApprovalRiskEngine
from app.manager.schemas import EscalationOut
from app.models import Claim


class EscalationService:
    def __init__(self, db: Session):
        self._db = db
        self._risk = ApprovalRiskEngine(db)

    def create(
        self,
        *,
        tenant_id: int,
        escalated_by: int,
        claim_id: int,
        reason: str,
        target_role: str = "finance_admin",
        approval_id: Optional[int] = None,
    ) -> EscalationOut:
        claim = self._db.query(Claim).filter(Claim.id == claim_id).first()
        if not claim:
            raise ValueError("Claim not found")

        risk = self._risk.score_claim(claim, policy=claim.policy)
        from app.manager.models import ApprovalEscalation

        row = ApprovalEscalation(
            tenant_id=tenant_id,
            claim_id=claim_id,
            approval_id=approval_id,
            escalated_by=escalated_by,
            target_role=target_role,
            reason=reason[:2000],
            risk_score=risk.risk_score,
            risk_flags=risk.risk_flags,
            status="open",
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return self._to_out(row)

    def list_open(
        self,
        *,
        tenant_id: int,
        target_role: Optional[str] = None,
        limit: int = 50,
    ) -> List[EscalationOut]:
        from app.manager.models import ApprovalEscalation

        q = self._db.query(ApprovalEscalation).filter(
            ApprovalEscalation.tenant_id == tenant_id,
            ApprovalEscalation.status == "open",
        )
        if target_role:
            q = q.filter(ApprovalEscalation.target_role == target_role)
        rows = q.order_by(ApprovalEscalation.created_at.desc()).limit(limit).all()
        return [self._to_out(r) for r in rows]

    def _to_out(self, row) -> EscalationOut:
        return EscalationOut(
            id=row.id,
            claim_id=row.claim_id,
            status=row.status,
            reason=row.reason,
            risk_score=row.risk_score,
            risk_flags=row.risk_flags or [],
            created_at=row.created_at,
        )
