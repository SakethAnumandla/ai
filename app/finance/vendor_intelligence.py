"""Vendor intelligence — concentration, growth, spikes."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.finance.scope import expense_base_query, is_company_scope
from app.models import Expense, ExpenseStatus, TransactionType, User


class VendorIntelligenceService:
    def __init__(self, db: Session):
        self._db = db

    def top_vendors(
        self,
        user: User,
        *,
        limit: int = 10,
        months: int = 1,
        department: Optional[str] = None,
    ) -> Dict[str, Any]:
        start = datetime.utcnow() - timedelta(days=30 * max(1, months))
        end = datetime.utcnow()
        rows = expense_base_query(
            self._db, user, start=start, end=end, department=department
        ).all()

        by_vendor: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"total": 0.0, "count": 0}
        )
        for e in rows:
            v = (e.vendor_name or "Unknown").strip()
            by_vendor[v]["total"] += e.bill_amount
            by_vendor[v]["count"] += 1

        total = sum(d["total"] for d in by_vendor.values()) or 1
        ranked = sorted(by_vendor.items(), key=lambda x: -x[1]["total"])[:limit]
        vendors = [
            {
                "vendor": name,
                "total": round(data["total"], 2),
                "count": data["count"],
                "share_pct": round(data["total"] / total * 100, 1),
            }
            for name, data in ranked
        ]
        top3_share = sum(v["share_pct"] for v in vendors[:3])
        names = ", ".join(v["vendor"] for v in vendors[:3])
        narrative = (
            f"{names} account for {top3_share:.0f}% of spend this period."
            if vendors
            else "No vendor spend in this period."
        )
        return {
            "vendors": vendors,
            "total_spend": round(total, 2),
            "top3_concentration_pct": round(top3_share, 1),
            "narrative": narrative,
            "period_months": months,
        }

    def spend_concentration(self, user: User, *, months: int = 3) -> Dict[str, Any]:
        data = self.top_vendors(user, limit=20, months=months)
        vendors = data["vendors"]
        hhi = 0.0
        for v in vendors:
            share = v["share_pct"] / 100
            hhi += share * share
        return {
            "herfindahl_index": round(hhi, 4),
            "interpretation": (
                "high concentration" if hhi > 0.25 else "moderate concentration"
            ),
            "top_vendors": vendors[:10],
        }

    def vendor_growth(
        self,
        user: User,
        *,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Month-over-month vendor spend change."""
        now = datetime.utcnow()
        cur_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_start = (cur_start - timedelta(days=1)).replace(day=1)

        def _by_vendor(start, end):
            agg: Dict[str, float] = defaultdict(float)
            for e in expense_base_query(self._db, user, start=start, end=end).all():
                agg[(e.vendor_name or "Unknown").strip()] += e.bill_amount
            return agg

        current = _by_vendor(cur_start, now)
        prior = _by_vendor(prev_start, cur_start)

        growth = []
        all_vendors = set(current) | set(prior)
        for v in all_vendors:
            c = current.get(v, 0)
            p = prior.get(v, 0)
            if p == 0 and c == 0:
                continue
            pct = round((c - p) / p * 100, 1) if p > 0 else 100.0
            growth.append({
                "vendor": v,
                "current_month": round(c, 2),
                "prior_month": round(p, 2),
                "growth_pct": pct,
            })
        growth.sort(key=lambda x: -abs(x["growth_pct"]))
        return {"vendor_growth": growth[:limit], "period": "month_over_month"}

    def suspicious_spikes(
        self,
        user: User,
        *,
        spike_multiplier: float = 2.0,
        limit: int = 10,
    ) -> Dict[str, Any]:
        growth = self.vendor_growth(user, limit=50)
        spikes = [
            g
            for g in growth["vendor_growth"]
            if g["prior_month"] > 500
            and g["current_month"] >= g["prior_month"] * spike_multiplier
        ]
        return {
            "spikes": spikes[:limit],
            "threshold_multiplier": spike_multiplier,
            "count": len(spikes),
        }
