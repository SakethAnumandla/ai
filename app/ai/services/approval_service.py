"""Approval workflow service for AI tools."""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.models import ApprovalStatus, Claim, ClaimApproval, User
from app.services.claim_service import ClaimService


class ApprovalService:
    def __init__(self, db: Session):
        self._db = db
        self._claims = ClaimService(db)

    def list_pending_for_approver(self, approver_id: int) -> List[Dict[str, Any]]:
        rows = (
            self._db.query(ClaimApproval)
            .options(joinedload(ClaimApproval.claim))
            .filter(
                ClaimApproval.approver_id == approver_id,
                ClaimApproval.status == ApprovalStatus.PENDING,
            )
            .order_by(ClaimApproval.assigned_at.asc())
            .all()
        )
        out = []
        for a in rows:
            if not self._claims.can_approver_act(a):
                continue
            c = a.claim
            out.append({
                "approval_id": a.id,
                "claim_id": c.id,
                "claim_number": c.claim_number,
                "bill_name": c.bill_name,
                "bill_amount": c.bill_amount,
                "vendor_name": c.vendor_name,
                "user_id": c.user_id,
            })
        return out

    def submit_decision(
        self,
        *,
        approval_id: int,
        approver_id: int,
        decision: str,
        comment: Optional[str] = None,
        approved_amount: Optional[float] = None,
    ) -> Claim:
        status = ApprovalStatus.APPROVED if decision == "approved" else ApprovalStatus.REJECTED
        self._claims.process_approval(
            approval_id,
            approver_id,
            status,
            comments=comment,
            approved_amount=approved_amount,
        )
        self._db.commit()
        approval = self._db.query(ClaimApproval).filter(ClaimApproval.id == approval_id).first()
        return (
            self._db.query(Claim)
            .options(joinedload(Claim.policy))
            .filter(Claim.id == approval.claim_id)
            .first()
        )
