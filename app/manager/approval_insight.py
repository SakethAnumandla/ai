"""Approval intelligence — summaries, grouping, flagged claims."""
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.manager.policy_explanation import PolicyExplanationService
from app.manager.risk_engine import ApprovalRiskEngine
from app.manager.prioritization import ApprovalPrioritizer
from app.manager.risk_explainability import RiskExplainabilityService
from app.manager.schemas import ApprovalCandidate, PrioritizedCandidate, QueueSummary
from app.models import ApprovalStatus, Claim, ClaimApproval, User
from app.services.claim_service import ClaimService


class ApprovalInsightService:
    def __init__(self, db: Session):
        self._db = db
        self._claims = ClaimService(db)
        self._risk = ApprovalRiskEngine(db)
        self._policy = PolicyExplanationService(db)
        self._prioritizer = ApprovalPrioritizer(db)
        self._risk_explain = RiskExplainabilityService()

    def list_actionable_pending(
        self, approver_id: int, *, prioritize: bool = True
    ) -> List[ApprovalCandidate]:
        rows = self._fetch_pending(approver_id)
        out: List[ApprovalCandidate] = []
        for approval in rows:
            if not self._claims.can_approver_act(approval):
                continue
            c = approval.claim
            submitter = c.user
            risk = self._risk.score_claim(c, policy=c.policy)
            policy_flags = []
            if risk.risk_score >= 0.35:
                try:
                    expl = self._policy.explain_claim(c.id)
                    policy_flags = expl.reasons[:3]
                except Exception:
                    pass
            breakdown = self._risk_explain.explain(risk)
            risk = risk.model_copy(
                update={
                    "details": {
                        **risk.details,
                        "risk_summary": breakdown.summary,
                        "risk_explanations": breakdown.explanations,
                    }
                }
            )
            out.append(
                ApprovalCandidate(
                    approval_id=approval.id,
                    claim_id=c.id,
                    claim_number=c.claim_number,
                    bill_name=c.bill_name,
                    bill_amount=c.bill_amount,
                    vendor_name=c.vendor_name,
                    main_category=c.main_category.value if c.main_category else None,
                    department=submitter.department.value if submitter and submitter.department else None,
                    submitter_name=(
                        (submitter.full_name or submitter.email or submitter.username)
                        if submitter
                        else None
                    ),
                    risk=risk,
                    policy_flags=policy_flags,
                )
            )
        if prioritize and out:
            return list(self._prioritizer.prioritize(out, approver_id=approver_id))
        return out

    def list_prioritized_pending(self, approver_id: int) -> List[PrioritizedCandidate]:
        rows = self.list_actionable_pending(approver_id, prioritize=True)
        return [r if isinstance(r, PrioritizedCandidate) else PrioritizedCandidate(**r.model_dump()) for r in rows]

    def summarize_queue(self, approver_id: int) -> QueueSummary:
        candidates = self.list_actionable_pending(approver_id)
        by_cat: Dict[str, int] = defaultdict(int)
        flagged = 0
        high_risk = 0
        total_value = 0.0

        for c in candidates:
            cat = c.main_category or "other"
            by_cat[cat] += 1
            total_value += c.bill_amount
            if c.risk.risk_score >= 0.5:
                high_risk += 1
            if c.policy_flags or c.risk.risk_score >= 0.35:
                flagged += 1

        groups = []
        for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
            cat_total = sum(
                x.bill_amount for x in candidates if (x.main_category or "other") == cat
            )
            groups.append({
                "category": cat,
                "count": count,
                "total_amount": round(cat_total, 2),
            })

        lines = [f"You have {len(candidates)} pending approval(s)."]
        for g in groups[:6]:
            lines.append(f"- {g['count']} {g['category']} claim(s)")
        if flagged:
            lines.append(f"{flagged} claim(s) are flagged for policy or risk review.")
        lines.append(f"Total pending value: ₹{total_value:,.2f}")

        return QueueSummary(
            total_pending=len(candidates),
            total_value=round(total_value, 2),
            by_category=dict(by_cat),
            flagged_count=flagged,
            high_risk_count=high_risk,
            summary_text=" ".join(lines),
            groups=groups,
        )

    def list_flagged(self, approver_id: int) -> List[ApprovalCandidate]:
        return [
            c
            for c in self.list_actionable_pending(approver_id)
            if c.risk.risk_score >= 0.35 or c.policy_flags
        ]

    def grouped_by_category(self, approver_id: int) -> Dict[str, List[ApprovalCandidate]]:
        grouped: Dict[str, List[ApprovalCandidate]] = defaultdict(list)
        for c in self.list_actionable_pending(approver_id):
            grouped[c.main_category or "other"].append(c)
        return dict(grouped)

    def _fetch_pending(self, approver_id: int) -> List[ClaimApproval]:
        return (
            self._db.query(ClaimApproval)
            .options(
                joinedload(ClaimApproval.claim).joinedload(Claim.policy),
                joinedload(ClaimApproval.claim).joinedload(Claim.user),
            )
            .filter(
                ClaimApproval.approver_id == approver_id,
                ClaimApproval.status == ApprovalStatus.PENDING,
            )
            .order_by(ClaimApproval.assigned_at.asc())
            .all()
        )
