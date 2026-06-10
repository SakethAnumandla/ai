"""Policy violation analytics — trends, departments, hotspots."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.finance.scope import is_company_scope
from app.models import Claim, ClaimStatus, Policy, User


class PolicyViolationAnalyticsService:
    def __init__(self, db: Session):
        self._db = db

    def violation_summary(
        self,
        user: User,
        *,
        months: int = 3,
    ) -> Dict[str, Any]:
        start = datetime.utcnow() - timedelta(days=30 * max(1, months))
        q = (
            self._db.query(Claim)
            .options(joinedload(Claim.policy), joinedload(Claim.user))
            .filter(Claim.submitted_at >= start)
        )
        if not is_company_scope(user) and user.department:
            q = q.join(User, Claim.user_id == User.id).filter(
                User.department == user.department
            )

        claims = q.limit(2000).all()
        violations = []
        for c in claims:
            if self._is_violation(c):
                violations.append(c)

        by_dept: Dict[str, int] = defaultdict(int)
        by_policy: Dict[str, int] = defaultdict(int)
        by_month: Dict[str, int] = defaultdict(int)

        for c in violations:
            dept = c.user.department.value if c.user and c.user.department else "unknown"
            pname = c.policy.policy_name if c.policy else "unknown"
            by_dept[dept] += 1
            by_policy[pname] += 1
            if c.submitted_at:
                by_month[c.submitted_at.strftime("%Y-%m")] += 1

        total_v = len(violations)
        total_c = len(claims) or 1
        dept_ranked = sorted(
            [{"department": d, "count": n, "share_pct": round(n / max(total_v, 1) * 100, 1)}
             for d, n in by_dept.items()],
            key=lambda x: -x["count"],
        )
        top_dept = dept_ranked[0] if dept_ranked else None
        narrative = ""
        if top_dept and total_v:
            narrative = (
                f"{top_dept['department'].title()} accounts for "
                f"{top_dept['share_pct']:.0f}% of policy violations this period."
            )

        return {
            "violation_count": total_v,
            "claim_count": len(claims),
            "violation_rate_pct": round(total_v / total_c * 100, 1),
            "by_department": dept_ranked,
            "by_policy": sorted(
                [{"policy": p, "count": n} for p, n in by_policy.items()],
                key=lambda x: -x["count"],
            )[:15],
            "by_month": dict(sorted(by_month.items())),
            "narrative": narrative,
            "hotspots": self._hotspots(by_dept, by_policy),
        }

    def department_ranking(self, user: User, *, months: int = 3) -> Dict[str, Any]:
        data = self.violation_summary(user, months=months)
        return {
            "ranking": data["by_department"],
            "narrative": data["narrative"],
        }

    def _is_violation(self, claim: Claim) -> bool:
        if claim.status == ClaimStatus.REJECTED:
            return True
        if claim.rejection_reason:
            return True
        if claim.deduction_reason and "exceeds" in (claim.deduction_reason or "").lower():
            return True
        if claim.policy and claim.bill_amount > claim.policy.maximum_amount:
            return True
        return False

    def _hotspots(
        self,
        by_dept: Dict[str, int],
        by_policy: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        hotspots = []
        for d, n in sorted(by_dept.items(), key=lambda x: -x[1])[:3]:
            hotspots.append({"type": "department", "name": d, "violations": n})
        for p, n in sorted(by_policy.items(), key=lambda x: -x[1])[:3]:
            hotspots.append({"type": "policy", "name": p, "violations": n})
        return hotspots
