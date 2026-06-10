"""Finance analytics — spend trends, categories, departments, quarters."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.finance.scope import expense_base_query, is_company_scope, period_range
from app.models import Expense, ExpenseStatus, MainCategory, TransactionType, User


class FinanceAnalyticsService:
    def __init__(self, db: Session):
        self._db = db

    def monthly_spend(
        self,
        user: User,
        *,
        months: int = 3,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        start, end = period_range(months=months)
        rows = expense_base_query(
            self._db, user, start=start, end=end, department=department
        ).all()
        return self._aggregate_period(rows, start, end, months=months)

    def spend_trends(
        self,
        user: User,
        *,
        quarters: int = 1,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Quarter-over-quarter style trend with narrative drivers."""
        start, end = period_range(quarters=max(1, quarters))
        rows = expense_base_query(
            self._db, user, start=start, end=end, department=department
        ).all()

        by_month: Dict[str, float] = defaultdict(float)
        by_category: Dict[str, float] = defaultdict(float)
        for e in rows:
            key = e.bill_date.strftime("%Y-%m") if e.bill_date else "unknown"
            by_month[key] += e.bill_amount
            cat = e.main_category.value if e.main_category else "other"
            by_category[cat] += e.bill_amount

        months_sorted = sorted(by_month.keys())
        total = sum(by_month.values())
        mom_changes: List[Dict[str, Any]] = []
        prev = None
        for m in months_sorted:
            val = by_month[m]
            pct = None
            if prev and prev > 0:
                pct = round((val - prev) / prev * 100, 1)
            mom_changes.append({"month": m, "spend": round(val, 2), "mom_pct": pct})
            prev = val

        # Current vs prior quarter approximation
        mid = len(months_sorted) // 2
        recent_months = months_sorted[mid:] if mid else months_sorted
        prior_months = months_sorted[:mid] if mid else []
        recent_total = sum(by_month.get(m, 0) for m in recent_months)
        prior_total = sum(by_month.get(m, 0) for m in prior_months) or 1
        qtr_pct = round((recent_total - prior_total) / prior_total * 100, 1)

        top_cats = sorted(by_category.items(), key=lambda x: -x[1])[:3]
        drivers = [c[0] for c in top_cats]

        narrative = self._trend_narrative(qtr_pct, drivers)
        return {
            "total_spend": round(total, 2),
            "expense_count": len(rows),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "by_month": {k: round(v, 2) for k, v in by_month.items()},
            "quarter_change_pct": qtr_pct,
            "month_over_month": mom_changes,
            "top_categories": [
                {"category": c, "total": round(v, 2)} for c, v in top_cats
            ],
            "narrative": narrative,
            "scope": "company" if is_company_scope(user) else "department",
        }

    def category_breakdown(
        self,
        user: User,
        *,
        months: int = 1,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        start, end = period_range(months=months)
        rows = expense_base_query(
            self._db, user, start=start, end=end, department=department
        ).all()
        total = sum(e.bill_amount for e in rows) or 1
        by_cat: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"total": 0.0, "count": 0})
        for e in rows:
            cat = e.main_category.value if e.main_category else "other"
            by_cat[cat]["total"] += e.bill_amount
            by_cat[cat]["count"] += 1

        categories = []
        for cat, data in sorted(by_cat.items(), key=lambda x: -x[1]["total"]):
            categories.append({
                "category": cat,
                "total": round(data["total"], 2),
                "count": data["count"],
                "share_pct": round(data["total"] / total * 100, 1),
            })
        return {
            "total_spend": round(sum(e.bill_amount for e in rows), 2),
            "period_months": months,
            "categories": categories,
        }

    def department_analysis(
        self,
        user: User,
        *,
        months: int = 3,
    ) -> Dict[str, Any]:
        if not is_company_scope(user):
            dept = user.department.value if user.department else "unknown"
            data = self.category_breakdown(user, months=months, department=dept)
            return {
                "departments": [{
                    "department": dept,
                    "total_spend": data["total_spend"],
                    "categories": data["categories"],
                }],
                "period_months": months,
            }

        start, end = period_range(months=months)
        rows = (
            self._db.query(
                User.department,
                func.sum(Expense.bill_amount).label("total"),
                func.count(Expense.id).label("cnt"),
            )
            .join(User, Expense.user_id == User.id)
            .filter(
                Expense.status == ExpenseStatus.APPROVED,
                Expense.transaction_type == TransactionType.EXPENSE,
                Expense.bill_date >= start,
                Expense.bill_date <= end,
            )
            .group_by(User.department)
            .all()
        )
        total = sum(float(r.total or 0) for r in rows) or 1
        departments = [
            {
                "department": r.department.value if r.department else "unknown",
                "total_spend": round(float(r.total or 0), 2),
                "expense_count": int(r.cnt or 0),
                "share_pct": round(float(r.total or 0) / total * 100, 1),
            }
            for r in sorted(rows, key=lambda x: float(x.total or 0), reverse=True)
        ]
        return {"departments": departments, "period_months": months, "total_spend": round(total, 2)}

    def department_trends(
        self,
        user: User,
        *,
        months: int = 6,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Per-department month-over-month spend."""
        start, end = period_range(months=months)
        q = (
            self._db.query(Expense)
            .join(User, Expense.user_id == User.id)
            .filter(
                Expense.status == ExpenseStatus.APPROVED,
                Expense.transaction_type == TransactionType.EXPENSE,
                Expense.bill_date >= start,
                Expense.bill_date <= end,
            )
        )
        if department:
            from app.models import Department
            try:
                q = q.filter(User.department == Department(department))
            except ValueError:
                pass
        elif not is_company_scope(user) and user.department:
            q = q.filter(User.department == user.department)

        by_dept_month: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for e in q.all():
            dept = "unknown"
            u = self._db.query(User).filter(User.id == e.user_id).first()
            if u and u.department:
                dept = u.department.value
            month = e.bill_date.strftime("%Y-%m") if e.bill_date else "unknown"
            by_dept_month[dept][month] += e.bill_amount

        trends = []
        for dept, months_map in sorted(by_dept_month.items()):
            series = sorted(months_map.items())
            mom = None
            if len(series) >= 2 and series[-2][1] > 0:
                mom = round((series[-1][1] - series[-2][1]) / series[-2][1] * 100, 1)
            trends.append({
                "department": dept,
                "by_month": {m: round(v, 2) for m, v in series},
                "latest_month_spend": round(series[-1][1], 2) if series else 0,
                "mom_pct": mom,
            })
        trends.sort(key=lambda x: -x["latest_month_spend"])
        return {"department_trends": trends, "period_months": months}

    def quarter_comparison(self, user: User) -> Dict[str, Any]:
        """Compare last 90 days vs prior 90 days."""
        end = datetime.utcnow()
        current_start = end - timedelta(days=90)
        prior_start = current_start - timedelta(days=90)

        def _total(s, e):
            return sum(
                e.bill_amount
                for e in expense_base_query(self._db, user, start=s, end=e).all()
            )

        current = _total(current_start, end)
        prior = _total(prior_start, current_start) or 1
        pct = round((current - prior) / prior * 100, 1)
        return {
            "current_quarter_spend": round(current, 2),
            "prior_quarter_spend": round(prior, 2),
            "change_pct": pct,
            "narrative": self._trend_narrative(pct, []),
        }

    def _aggregate_period(
        self, rows: List[Expense], start: datetime, end: datetime, *, months: int
    ) -> Dict[str, Any]:
        total = sum(e.bill_amount for e in rows)
        by_month: Dict[str, float] = defaultdict(float)
        for e in rows:
            key = e.bill_date.strftime("%Y-%m") if e.bill_date else "unknown"
            by_month[key] += e.bill_amount
        return {
            "total_spend": round(total, 2),
            "expense_count": len(rows),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "by_month": {k: round(v, 2) for k, v in by_month.items()},
            "months": months,
        }

    def _trend_narrative(self, change_pct: float, top_categories: List[str]) -> str:
        direction = "increased" if change_pct > 0 else "decreased"
        if abs(change_pct) < 2:
            base = "Company spend is relatively flat this period."
        else:
            base = f"Company spend {direction} {abs(change_pct):.0f}% this period."
        if top_categories:
            cats = ", ".join(top_categories[:3])
            base += f" Primary drivers: {cats}."
        return base
