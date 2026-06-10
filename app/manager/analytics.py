"""Manager analytics — team spend, delays, vendor patterns, department risk."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.manager.risk_engine import ApprovalRiskEngine
from app.models import (
    ApprovalStatus,
    Claim,
    ClaimApproval,
    ClaimStatus,
    Department,
    Expense,
    ExpenseStatus,
    MainCategory,
    TransactionType,
    User,
    UserRole,
)


class ManagerAnalyticsService:
    def __init__(self, db: Session):
        self._db = db
        self._risk = ApprovalRiskEngine(db)

    def team_spend(
        self,
        manager: User,
        *,
        months: int = 1,
        main_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        end = datetime.utcnow()
        start = end - timedelta(days=30 * max(1, months))
        user_ids = self._team_user_ids(manager)

        q = self._db.query(Expense).filter(
            Expense.user_id.in_(user_ids),
            Expense.status == ExpenseStatus.APPROVED,
            Expense.transaction_type == TransactionType.EXPENSE,
            Expense.bill_date >= start,
        )
        if main_category:
            q = q.filter(Expense.main_category == MainCategory(main_category))

        rows = q.all()
        total = sum(e.bill_amount for e in rows)
        by_cat: Dict[str, float] = defaultdict(float)
        for e in rows:
            cat = e.main_category.value if e.main_category else "other"
            by_cat[cat] += e.bill_amount

        return {
            "total_spend": round(total, 2),
            "expense_count": len(rows),
            "period_months": months,
            "department": manager.department.value if manager.department else None,
            "by_category": {k: round(v, 2) for k, v in sorted(by_cat.items(), key=lambda x: -x[1])},
        }

    def department_meal_budget_pressure(self, manager: User) -> Dict[str, Any]:
        """Which departments exceed meal spend vs a simple benchmark."""
        end = datetime.utcnow()
        start = end - timedelta(days=30)
        rows = (
            self._db.query(
                User.department,
                func.sum(Expense.bill_amount).label("total"),
                func.count(Expense.id).label("cnt"),
            )
            .join(User, Expense.user_id == User.id)
            .filter(
                Expense.status == ExpenseStatus.APPROVED,
                Expense.main_category == MainCategory.FOOD,
                Expense.bill_date >= start,
            )
            .group_by(User.department)
            .all()
        )
        ranked = [
            {
                "department": r.department.value if r.department else "unknown",
                "meal_spend": round(float(r.total or 0), 2),
                "claim_count": int(r.cnt or 0),
            }
            for r in sorted(rows, key=lambda x: float(x.total or 0), reverse=True)
        ]
        return {"period_days": 30, "departments": ranked}

    def approval_delays(self, approver_id: int) -> Dict[str, Any]:
        rows = (
            self._db.query(ClaimApproval)
            .filter(
                ClaimApproval.approver_id == approver_id,
                ClaimApproval.status == ApprovalStatus.PENDING,
            )
            .all()
        )
        now = datetime.utcnow()
        delays = []
        for a in rows:
            assigned = a.assigned_at
            if assigned and assigned.tzinfo:
                assigned = assigned.replace(tzinfo=None)
            hours = (now - assigned).total_seconds() / 3600 if assigned else 0
            delays.append({
                "approval_id": a.id,
                "claim_id": a.claim_id,
                "hours_waiting": round(hours, 1),
            })
        delays.sort(key=lambda x: -x["hours_waiting"])
        avg = sum(d["hours_waiting"] for d in delays) / max(len(delays), 1)
        return {
            "pending_count": len(delays),
            "average_hours_waiting": round(avg, 1),
            "slowest": delays[:5],
        }

    def vendor_patterns(
        self,
        manager: User,
        *,
        limit: int = 10,
        quarter: bool = True,
    ) -> Dict[str, Any]:
        days = 90 if quarter else 30
        start = datetime.utcnow() - timedelta(days=days)
        user_ids = self._team_user_ids(manager)

        rows = (
            self._db.query(
                Expense.vendor_name,
                func.sum(Expense.bill_amount).label("total"),
                func.count(Expense.id).label("cnt"),
            )
            .filter(
                Expense.user_id.in_(user_ids),
                Expense.status == ExpenseStatus.APPROVED,
                Expense.bill_date >= start,
            )
            .group_by(Expense.vendor_name)
            .order_by(func.sum(Expense.bill_amount).desc())
            .limit(limit)
            .all()
        )
        return {
            "period_days": days,
            "vendors": [
                {
                    "vendor": r.vendor_name or "Unknown",
                    "total": round(float(r.total or 0), 2),
                    "count": int(r.cnt or 0),
                }
                for r in rows
            ],
        }

    def department_risk_summary(self, manager: User) -> Dict[str, Any]:
        pending = (
            self._db.query(Claim)
            .join(User, Claim.user_id == User.id)
            .filter(Claim.status == ClaimStatus.PENDING)
        )
        if manager.department:
            pending = pending.filter(User.department == manager.department)
        claims = pending.limit(100).all()

        by_dept: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "avg_risk": 0.0, "flags": []}
        )
        for claim in claims:
            dept = claim.user.department.value if claim.user and claim.user.department else "unknown"
            risk = self._risk.score_claim(claim, policy=claim.policy)
            bucket = by_dept[dept]
            bucket["count"] += 1
            bucket["avg_risk"] += risk.risk_score
            bucket["flags"].extend(risk.risk_flags)

        for dept, bucket in by_dept.items():
            if bucket["count"]:
                bucket["avg_risk"] = round(bucket["avg_risk"] / bucket["count"], 3)
            bucket["flags"] = list(dict.fromkeys(bucket["flags"]))[:10]

        return {"departments": dict(by_dept)}

    def _team_user_ids(self, manager: User) -> List[int]:
        q = self._db.query(User.id).filter(User.is_active.is_(True))
        if manager.role in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN):
            return [r[0] for r in q.all()]
        if manager.department:
            q = q.filter(User.department == manager.department)
        else:
            reports = q.filter(User.manager_id == manager.id).all()
            if reports:
                return [r[0] for r in reports]
            return [manager.id]
        return [r[0] for r in q.all()]
