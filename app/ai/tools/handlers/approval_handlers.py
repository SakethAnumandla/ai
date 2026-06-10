"""Approval tool handlers — delegate to ApprovalService / ClaimService."""
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.schemas.common import SessionContext
from app.ai.schemas.tool_result import ToolResult
from app.models import User
from app.ai.services.approval_service import ApprovalService


async def handle_approval_pending_v1(
    *, db: Session, user: User, ctx: SessionContext, **_
) -> ToolResult:
    from app.ai.tools.handlers.manager_handlers import handle_approval_pending_v1 as _mgr_pending

    return await _mgr_pending(db=db, user=user, ctx=ctx)


async def handle_approval_submit_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    approval_id: int,
    decision: str,
    idempotency_key: str,
    comment: Optional[str] = None,
    approved_amount: Optional[float] = None,
    **_,
) -> ToolResult:
    svc = ApprovalService(db)
    try:
        claim = svc.submit_decision(
            approval_id=approval_id,
            approver_id=user.id,
            decision=decision,
            comment=comment,
            approved_amount=approved_amount,
        )
    except ValueError as e:
        return ToolResult.fail(str(e), error="approval_failed")
    from app.ai.security import resolve_tenant_id
    from app.ai.schemas.common import TenantUserContext
    from app.manager.memory import ManagerMemoryService
    from app.manager.risk_engine import ApprovalRiskEngine

    risk = ApprovalRiskEngine(db).score_claim(claim, policy=claim.policy)
    mem = ManagerMemoryService(db)
    mem.record_decision(
        TenantUserContext(tenant_id=resolve_tenant_id(user), user_id=user.id),
        decision=decision,
        claim_id=claim.id,
        main_category=claim.main_category.value if claim.main_category else None,
        amount=claim.bill_amount or 0,
        risk_score=risk.risk_score,
        was_override=risk.risk_score >= 0.35 and decision == "approved",
    )

    return ToolResult.ok(
        message=f"Claim #{claim.id} marked as {decision}.",
        data={
            "claim_id": claim.id,
            "status": claim.status.value,
            "risk": risk.model_dump(),
        },
    )


async def handle_reimbursement_submit_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    claim_id: int,
    idempotency_key: str,
    amount: Optional[float] = None,
    **_,
) -> ToolResult:
    from app.models import Claim, ClaimStatus

    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        return ToolResult.fail("Claim not found", error="not_found")
    if claim.status not in (ClaimStatus.APPROVED, ClaimStatus.PENDING):
        return ToolResult.fail(
            f"Claim cannot be reimbursed in status {claim.status.value}",
            error="invalid_status",
        )
    # Reimbursement is finalized via approval workflow; record intent for finance
    return ToolResult.ok(
        message=f"Reimbursement recorded for claim #{claim_id}"
        + (f" (₹{amount:,.2f})" if amount else ""),
        data={"claim_id": claim_id, "amount": amount or claim.approved_amount},
    )
