"""Approval simulation — policy/budget impact before executing."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.manager.approval_insight import ApprovalInsightService
from app.manager.schemas import ApprovalCandidate, BulkApprovalFilters, SimulationResult, SimulationWarning
from app.manager.bulk_planner import BulkApprovalPlanner
from app.models import Department, Expense, ExpenseStatus, MainCategory, TransactionType, User


class ApprovalSimulationService:
    """
    Simulate impact if pending claims are approved (no DB mutations).
    """

    def __init__(self, db: Session):
        self._db = db
        self._planner = BulkApprovalPlanner(db)
        self._insight = ApprovalInsightService(db)
        self._meal_budget = getattr(settings, "manager_department_meal_budget_monthly", 50000.0)
        self._travel_budget = getattr(settings, "manager_department_travel_budget_monthly", 200000.0)

    def simulate_bulk_approve(
        self,
        approver: User,
        *,
        filters: Optional[BulkApprovalFilters] = None,
        approval_ids: Optional[List[int]] = None,
    ) -> SimulationResult:
        if approval_ids:
            pending = {c.approval_id: c for c in self._insight.list_actionable_pending(approver.id)}
            candidates = [pending[aid] for aid in approval_ids if aid in pending]
        elif filters:
            candidates = self._planner._apply_filters(approver.id, filters)
        else:
            candidates = self._insight.list_actionable_pending(approver.id)

        total = sum(c.bill_amount for c in candidates)
        warnings: List[SimulationWarning] = []

        by_dept_cat: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for c in candidates:
            dept = c.department or "unknown"
            cat = c.main_category or "other"
            by_dept_cat[dept][cat] += c.bill_amount

        for dept, cats in by_dept_cat.items():
            for cat, add in cats.items():
                projected = self._current_dept_category_spend(dept, cat) + add
                budget, label = self._budget_for_category(cat)
                if budget and projected > budget:
                    warnings.append(
                        SimulationWarning(
                            severity="high",
                            code="department_budget_exceeded",
                            message=(
                                f"If approved, {dept} {label} spend this month would reach "
                                f"₹{projected:,.2f} (benchmark ₹{budget:,.2f})."
                            ),
                            department=dept,
                            category=cat,
                            projected_spend=round(projected, 2),
                            budget_limit=budget,
                        )
                    )

        for c in candidates:
            if c.risk.risk_score >= 0.7:
                warnings.append(
                    SimulationWarning(
                        severity="medium",
                        code="high_risk_approval",
                        message=(
                            f"Claim {c.claim_number} (₹{c.bill_amount:,.2f}) has "
                            f"risk score {c.risk.risk_score:.0%}."
                        ),
                        claim_id=c.claim_id,
                    )
                )
            if c.policy_flags:
                warnings.append(
                    SimulationWarning(
                        severity="medium",
                        code="policy_review",
                        message=f"Claim {c.claim_number} has open policy flags.",
                        claim_id=c.claim_id,
                    )
                )

        would_exceed = any(w.code == "department_budget_exceeded" for w in warnings)
        summary_parts = [
            f"Simulating approval of {len(candidates)} claim(s), total ₹{total:,.2f}.",
        ]
        if would_exceed:
            summary_parts.append("One or more department category budgets would be exceeded.")
        if not warnings:
            summary_parts.append("No budget or policy blockers detected in simulation.")
        else:
            summary_parts.append(f"{len(warnings)} warning(s) — review before confirming.")

        return SimulationResult(
            action="approve",
            candidate_count=len(candidates),
            total_amount=round(total, 2),
            warnings=warnings,
            would_exceed_budget=would_exceed,
            summary_text=" ".join(summary_parts),
            candidates=[c.model_dump(mode="json") for c in candidates[:50]],
        )

    def _current_dept_category_spend(self, department: str, category: str) -> float:
        start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        try:
            main_cat = MainCategory(category)
        except ValueError:
            return 0.0

        try:
            dept_enum = Department(department)
        except ValueError:
            return 0.0

        total = (
            self._db.query(func.coalesce(func.sum(Expense.bill_amount), 0))
            .join(User, Expense.user_id == User.id)
            .filter(
                User.department == dept_enum,
                Expense.main_category == main_cat,
                Expense.status == ExpenseStatus.APPROVED,
                Expense.transaction_type == TransactionType.EXPENSE,
                Expense.bill_date >= start,
            )
            .scalar()
        )
        return float(total or 0)

    def _budget_for_category(self, category: str) -> tuple:
        if category == "food":
            return self._meal_budget, "meal"
        if category == "travel":
            return self._travel_budget, "travel"
        return None, category
