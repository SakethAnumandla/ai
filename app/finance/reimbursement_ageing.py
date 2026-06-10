"""Reimbursement ageing — pending, blocked, SLA risk."""
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.finance.scope import is_company_scope
from app.models import ApprovalStatus, Claim, ClaimApproval, ClaimStatus, User


class ReimbursementAgeingService:
    def __init__(self, db: Session):
        self._db = db
        self._sla_hours = getattr(settings, "manager_approval_urgent_hours", 48.0)

    def ageing_report(self, user: User) -> Dict[str, Any]:
        q = (
            self._db.query(Claim)
            .options(joinedload(Claim.user), joinedload(Claim.approvals))
        )
        if not is_company_scope(user) and user.department:
            q = q.join(User, Claim.user_id == User.id).filter(
                User.department == user.department
            )

        now = datetime.utcnow()
        pending_reimb: List[Dict[str, Any]] = []
        blocked: List[Dict[str, Any]] = []
        at_risk: List[Dict[str, Any]] = []

        for status in (ClaimStatus.PENDING, ClaimStatus.APPROVED):
            for claim in q.filter(Claim.status == status).limit(500).all():
                if claim.status == ClaimStatus.REIMBURSED:
                    continue
                submitted = claim.submitted_at
                if submitted and submitted.tzinfo:
                    submitted = submitted.replace(tzinfo=None)
                hours = (now - submitted).total_seconds() / 3600 if submitted else 0

                pending_approvals = [
                    a for a in (claim.approvals or [])
                    if a.status == ApprovalStatus.PENDING
                ]
                if pending_approvals:
                    oldest = min(
                        pending_approvals,
                        key=lambda a: a.assigned_at or now,
                    )
                    assigned = oldest.assigned_at
                    if assigned and assigned.tzinfo:
                        assigned = assigned.replace(tzinfo=None)
                    wait = (now - assigned).total_seconds() / 3600 if assigned else hours
                    if wait >= self._sla_hours * 0.75:
                        dept = (
                            claim.user.department.value
                            if claim.user and claim.user.department
                            else "unknown"
                        )
                        at_risk.append({
                            "claim_id": claim.id,
                            "claim_number": claim.claim_number,
                            "department": dept,
                            "hours_waiting": round(wait, 1),
                            "amount": claim.bill_amount,
                            "status": claim.status.value,
                        })
                    if claim.status == ClaimStatus.PENDING:
                        blocked.append({
                            "claim_id": claim.id,
                            "claim_number": claim.claim_number,
                            "reason": "awaiting_approval",
                            "hours": round(wait, 1),
                        })
                elif claim.status == ClaimStatus.APPROVED and not claim.reimbursed_at:
                    pending_reimb.append({
                        "claim_id": claim.id,
                        "claim_number": claim.claim_number,
                        "amount": claim.approved_amount or claim.bill_amount,
                        "hours_since_approval": round(hours, 1),
                    })

        at_risk.sort(key=lambda x: -x["hours_waiting"])
        buckets = self._age_buckets(pending_reimb + blocked)
        narrative = self._ageing_narrative(at_risk, pending_reimb)

        return {
            "pending_reimbursement": pending_reimb[:25],
            "blocked": blocked[:25],
            "sla_at_risk": at_risk[:25],
            "sla_at_risk_count": len(at_risk),
            "age_buckets": buckets,
            "narrative": narrative,
        }

    def _age_buckets(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        buckets = {"0-24h": 0, "24-72h": 0, "72h+": 0}
        for item in items:
            h = item.get("hours") or item.get("hours_since_approval") or 0
            if h < 24:
                buckets["0-24h"] += 1
            elif h < 72:
                buckets["24-72h"] += 1
            else:
                buckets["72h+"] += 1
        return buckets

    def _ageing_narrative(
        self, at_risk: List[Dict[str, Any]], pending: List[Dict[str, Any]]
    ) -> str:
        if not at_risk and not pending:
            return "No significant reimbursement ageing detected."
        parts = []
        if at_risk:
            depts = list(dict.fromkeys(a["department"] for a in at_risk[:10]))
            parts.append(
                f"{len(at_risk)} reimbursement(s) at risk of breaching SLA within "
                f"{max(1, int(self._sla_hours / 24))} day(s), primarily in "
                f"{', '.join(depts[:3])}."
            )
        if pending:
            parts.append(f"{len(pending)} approved claim(s) awaiting reimbursement.")
        return " ".join(parts)
