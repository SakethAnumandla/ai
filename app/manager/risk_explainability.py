"""Risk score explainability — why risk_score is N."""
from typing import Any, Dict, List, Optional, Tuple

from app.manager.schemas import RiskAssessment, RiskScoreBreakdown
from app.models import Claim, Policy


# Weight map — must match ApprovalRiskEngine contributions
_FLAG_WEIGHTS: Dict[str, Tuple[float, str]] = {
    "policy_limit_exceeded": (
        0.35,
        "Bill amount exceeds the policy maximum limit.",
    ),
    "high_amount": (
        0.25,
        "Amount is above the high-value threshold for automatic approval.",
    ),
    "missing_invoice": (
        0.2,
        "No receipt or invoice file is attached.",
    ),
    "partial_coverage": (
        0.1,
        "Approved/covered amount is reduced vs claimed amount.",
    ),
    "abnormal_reimbursement": (
        0.15,
        "Approved reimbursement is far below the claimed amount.",
    ),
    "suspicious_timing": (
        0.1,
        "Submitted on a weekend or outside typical business hours.",
    ),
    "duplicate_vendor": (
        0.2,
        "Same vendor appears on multiple recent claims from this employee.",
    ),
    "repeated_policy_violations": (
        0.15,
        "Employee has prior rejected/violation claims on this policy.",
    ),
}


class RiskExplainabilityService:
    def explain(self, assessment: RiskAssessment) -> RiskScoreBreakdown:
        contributions: Dict[str, float] = {}
        explanations: List[str] = []

        for flag in assessment.risk_flags:
            weight, template = _FLAG_WEIGHTS.get(flag, (0.05, f"Risk signal: {flag.replace('_', ' ')}."))
            contributions[flag] = weight
            detail = assessment.details.get(flag) or assessment.details
            line = template
            if flag == "policy_limit_exceeded" and assessment.details.get("policy_max"):
                line = (
                    f"Bill exceeds policy limit (max ₹{assessment.details['policy_max']:,.2f})."
                )
            elif flag == "duplicate_vendor" and isinstance(assessment.details.get("duplicate_vendor"), dict):
                dv = assessment.details["duplicate_vendor"]
                line = (
                    f"Vendor '{dv.get('vendor')}' seen on {dv.get('recent_count', 2)} "
                    f"recent claims (+{weight:.0%} risk)."
                )
            elif flag == "high_amount" and assessment.details.get("amount"):
                line = f"High amount ₹{assessment.details['amount']:,.2f} (+{weight:.0%} risk)."
            else:
                line = f"{template} (+{weight:.0%} to risk score)."
            explanations.append(line)

        computed = min(1.0, round(sum(contributions.values()), 3))
        summary = self._build_summary(assessment.risk_score, computed, explanations)

        return RiskScoreBreakdown(
            risk_score=assessment.risk_score,
            risk_flags=assessment.risk_flags,
            contributions=contributions,
            explanations=explanations,
            summary=summary,
        )

    def explain_claim(self, assessment: RiskAssessment, claim: Claim, policy: Optional[Policy] = None) -> RiskScoreBreakdown:
        breakdown = self.explain(assessment)
        if policy and claim.bill_amount > policy.maximum_amount:
            breakdown.grounded_facts["policy_name"] = policy.policy_name
            breakdown.grounded_facts["policy_maximum"] = policy.maximum_amount
            breakdown.grounded_facts["bill_amount"] = claim.bill_amount
        breakdown.grounded_facts["claim_id"] = claim.id
        breakdown.grounded_facts["claim_number"] = claim.claim_number
        return breakdown

    def _build_summary(self, score: float, computed: float, explanations: List[str]) -> str:
        if not explanations:
            return f"Risk score is {score:.0%} — no significant risk flags detected."
        top = explanations[:3]
        body = " ".join(top)
        if score >= 0.7:
            prefix = f"Risk score is {score:.0%} (high). "
        elif score >= 0.4:
            prefix = f"Risk score is {score:.0%} (medium). "
        else:
            prefix = f"Risk score is {score:.0%} (low). "
        return prefix + body
