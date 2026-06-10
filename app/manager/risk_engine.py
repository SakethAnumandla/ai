"""Approval risk scoring for manager review."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.manager.schemas import RiskAssessment
from app.models import (
    ApprovalStatus,
    Claim,
    ClaimApproval,
    ClaimStatus,
    Policy,
    User,
)


class ApprovalRiskEngine:
    def __init__(self, db: Session):
        self._db = db
        self._high_amount = getattr(settings, "ai_high_amount_threshold", 50000.0)

    def score_claim(self, claim: Claim, *, policy: Optional[Policy] = None) -> RiskAssessment:
        flags: List[str] = []
        details: Dict[str, Any] = {}
        score = 0.0

        if policy is None and claim.policy_id:
            policy = claim.policy

        if policy and claim.bill_amount > policy.maximum_amount:
            flags.append("policy_limit_exceeded")
            details["policy_max"] = policy.maximum_amount
            score += 0.35

        if claim.bill_amount >= self._high_amount:
            flags.append("high_amount")
            details["amount"] = claim.bill_amount
            score += 0.25

        if not claim.file_data and not claim.file_name:
            flags.append("missing_invoice")
            score += 0.2

        if claim.deduction_reason:
            flags.append("partial_coverage")
            details["deduction_reason"] = claim.deduction_reason
            score += 0.1

        if claim.claimed_amount and claim.approved_amount:
            if claim.approved_amount < claim.claimed_amount * 0.5:
                flags.append("abnormal_reimbursement")
                score += 0.15

        if self._is_suspicious_timing(claim):
            flags.append("suspicious_timing")
            score += 0.1

        dup = self._duplicate_vendor_signal(claim)
        if dup:
            flags.append("duplicate_vendor")
            details["duplicate_vendor"] = dup
            score += 0.2

        violations = self._repeated_policy_violations(claim.user_id, policy)
        if violations:
            flags.append("repeated_policy_violations")
            details["prior_violations"] = violations
            score += 0.15

        score = min(1.0, round(score, 3))
        return RiskAssessment(risk_score=score, risk_flags=list(dict.fromkeys(flags)), details=details)

    def score_approval_row(self, approval: ClaimApproval) -> RiskAssessment:
        claim = approval.claim
        if not claim:
            return RiskAssessment(risk_score=0.0, risk_flags=[])
        return self.score_claim(claim, policy=claim.policy)

    def _is_suspicious_timing(self, claim: Claim) -> bool:
        ts = claim.submitted_at or claim.bill_date
        if not ts:
            return False
        if ts.tzinfo:
            ts = ts.replace(tzinfo=None)
        return ts.weekday() >= 5

    def _duplicate_vendor_signal(self, claim: Claim) -> Optional[Dict[str, Any]]:
        if not claim.vendor_name:
            return None
        window = datetime.utcnow() - timedelta(days=30)
        others = (
            self._db.query(Claim)
            .filter(
                Claim.user_id == claim.user_id,
                Claim.id != claim.id,
                Claim.vendor_name == claim.vendor_name,
                Claim.submitted_at >= window,
            )
            .limit(5)
            .all()
        )
        if len(others) >= 2:
            return {"vendor": claim.vendor_name, "recent_count": len(others) + 1}
        return None

    def _repeated_policy_violations(self, user_id: int, policy: Optional[Policy]) -> int:
        if not policy:
            return 0
        since = datetime.utcnow() - timedelta(days=90)
        count = (
            self._db.query(Claim)
            .filter(
                Claim.user_id == user_id,
                Claim.policy_id == policy.id,
                Claim.submitted_at >= since,
                Claim.rejection_reason.isnot(None),
            )
            .count()
        )
        return count if count >= 2 else 0
