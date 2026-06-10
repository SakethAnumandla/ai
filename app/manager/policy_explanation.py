"""Grounded policy explanations for flagged claims."""
from typing import List, Optional

from sqlalchemy.orm import Session, joinedload

from app.manager.risk_engine import ApprovalRiskEngine
from app.manager.schemas import PolicyExplanation
from app.models import Claim, Policy


class PolicyExplanationService:
    def __init__(self, db: Session):
        self._db = db
        self._risk = ApprovalRiskEngine(db)

    def explain_claim(self, claim_id: int, *, approver_id: Optional[int] = None) -> PolicyExplanation:
        q = (
            self._db.query(Claim)
            .options(joinedload(Claim.policy))
            .filter(Claim.id == claim_id)
        )
        claim = q.first()
        if not claim:
            raise ValueError(f"Claim #{claim_id} not found")

        policy: Optional[Policy] = claim.policy
        reasons: List[str] = []
        grounded: dict = {
            "bill_amount": claim.bill_amount,
            "claimed_amount": claim.claimed_amount,
            "approved_amount": claim.approved_amount,
            "vendor_name": claim.vendor_name,
            "has_attachment": bool(claim.file_data or claim.file_name),
        }

        if policy:
            grounded["policy_name"] = policy.policy_name
            grounded["policy_maximum"] = policy.maximum_amount
            if claim.bill_amount > policy.maximum_amount:
                reasons.append(
                    f"This expense (₹{claim.bill_amount:,.2f}) exceeds the "
                    f"₹{policy.maximum_amount:,.2f} policy limit for {policy.policy_name}."
                )
            if claim.deduction_reason:
                reasons.append(f"Coverage adjustment: {claim.deduction_reason}")
            if policy.exclusions:
                reasons.append(
                    f"Policy exclusions may apply: {policy.exclusions[:200]}"
                    + ("…" if len(policy.exclusions or "") > 200 else "")
                )
            docs = policy.documentation_required
            if docs and not grounded["has_attachment"]:
                reasons.append(
                    "Required documentation (e.g. GST invoice) was not attached."
                )

        if claim.rejection_reason:
            reasons.append(claim.rejection_reason)

        risk = self._risk.score_claim(claim, policy=policy)
        for flag in risk.risk_flags:
            if flag == "missing_invoice" and "documentation" not in " ".join(reasons).lower():
                reasons.append("No receipt or invoice file was uploaded with this claim.")
            elif flag == "duplicate_vendor":
                reasons.append(
                    "This vendor appears repeatedly on recent claims from the same employee."
                )
            elif flag == "high_amount":
                reasons.append(
                    f"Amount is flagged as high relative to typical claims (₹{claim.bill_amount:,.2f})."
                )
            elif flag == "suspicious_timing":
                reasons.append("Submitted outside typical business hours or on a weekend.")

        ocr = claim.ocr_data or {}
        if ocr.get("review_status") == "pending_review":
            reasons.append("OCR extraction requires human review (low confidence or fraud checks).")
        fraud = ocr.get("fraud_checks") or []
        for check in fraud:
            if isinstance(check, dict) and not check.get("passed", True):
                reasons.append(check.get("message", "Receipt fraud check failed."))

        if not reasons:
            reasons.append(
                "No policy violations detected on record; claim may be flagged for manager review only."
            )

        return PolicyExplanation(
            claim_id=claim.id,
            claim_number=claim.claim_number,
            flagged=bool(reasons) and risk.risk_score >= 0.35,
            reasons=reasons,
            policy_name=policy.policy_name if policy else None,
            policy_limit=policy.maximum_amount if policy else None,
            grounded_facts=grounded,
        )

    def explain_by_approval(self, approval_id: int, approver_id: int) -> PolicyExplanation:
        from app.models import ClaimApproval

        row = (
            self._db.query(ClaimApproval)
            .filter(
                ClaimApproval.id == approval_id,
                ClaimApproval.approver_id == approver_id,
            )
            .first()
        )
        if not row:
            raise ValueError("Approval not found or not authorized")
        return self.explain_claim(row.claim_id, approver_id=approver_id)
