"""Claim approval actions for department heads and managers."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_user
from app.models import ApprovalStatus, Claim, ClaimApproval, User
from app.schemas import ApprovalWorkflowResponse, ClaimApprovalResponse, ClaimApprovalUpdate, ClaimResponse
from app.services.claim_service import ClaimService

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _claim_to_response(claim: Claim) -> ClaimResponse:
    return ClaimResponse.model_validate(claim)


@router.get("/pending", response_model=list[ClaimApprovalResponse])
async def list_my_pending_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approvals assigned to the current user that can be actioned now."""
    claim_service = ClaimService(db)
    rows = (
        db.query(ClaimApproval)
        .options(joinedload(ClaimApproval.claim))
        .filter(
            ClaimApproval.approver_id == current_user.id,
            ClaimApproval.status == ApprovalStatus.PENDING,
        )
        .order_by(ClaimApproval.assigned_at.asc())
        .all()
    )
    return [a for a in rows if claim_service.can_approver_act(a)]


@router.get("/claim/{claim_id}/workflow", response_model=ApprovalWorkflowResponse)
async def get_claim_workflow(
    claim_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.user_id != current_user.id and not current_user.is_admin:
        is_approver = (
            db.query(ClaimApproval)
            .filter(
                ClaimApproval.claim_id == claim_id,
                ClaimApproval.approver_id == current_user.id,
            )
            .first()
        )
        if not is_approver:
            raise HTTPException(status_code=403, detail="Permission denied")

    claim_service = ClaimService(db)
    data = claim_service.get_claim_approval_status(claim_id)
    return ApprovalWorkflowResponse(
        claim_id=claim_id,
        total_approvals=data["total_approvals"],
        completed_approvals=data["completed_approvals"],
        pending_approvals=data["pending_approvals"],
        approval_details=[
            ClaimApprovalResponse.model_validate(a) for a in data["approval_details"]
        ],
    )


@router.post("/{approval_id}/action", response_model=ClaimResponse)
async def action_approval(
    approval_id: int,
    body: ClaimApprovalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve or reject a claim at department-head or manager level."""
    claim_service = ClaimService(db)
    try:
        claim_service.process_approval(
            approval_id,
            current_user.id,
            body.status,
            comments=body.comments,
            approved_amount=body.approved_amount,
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    approval = db.query(ClaimApproval).filter(ClaimApproval.id == approval_id).first()
    claim = (
        db.query(Claim)
        .options(joinedload(Claim.approvals), joinedload(Claim.policy))
        .filter(Claim.id == approval.claim_id)
        .first()
    )
    return _claim_to_response(claim)
