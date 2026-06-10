"""Analytics snapshots — immutable historical storage for executive reporting."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.security import resolve_tenant_id
from app.finance.models import AnalyticsSnapshot
from app.finance.services import FinanceAnalyticsFacade
from app.finance.snapshot_immutability import (
    ImmutableSnapshotGuard,
    seal_snapshot,
    verify_snapshot_integrity,
)
from app.models import User


class AnalyticsSnapshotService:
    def __init__(self, db: Session):
        self._db = db
        self._facade = FinanceAnalyticsFacade(db)

    def capture(
        self,
        user: User,
        snapshot_type: str,
        *,
        period_label: Optional[str] = None,
        department: Optional[str] = None,
        months: int = 3,
        quarters: int = 1,
        immutable: bool = True,
        executive: bool = False,
    ) -> AnalyticsSnapshot:
        tenant_id = resolve_tenant_id(user)
        period_label = period_label or datetime.now(timezone.utc).strftime("%Y-%m")

        payload = self._build_payload(
            user,
            snapshot_type,
            department=department,
            months=months,
            quarters=quarters,
        )
        summary = payload.get("narrative") or payload.get("summary_text") or ""

        row = AnalyticsSnapshot(
            tenant_id=tenant_id,
            created_by=user.id,
            snapshot_type=snapshot_type,
            period_label=period_label,
            department=department,
            payload=payload,
            summary_text=summary[:2000] if summary else None,
            immutable=False,
        )
        if immutable:
            seal_snapshot(row, executive=executive or snapshot_type == "executive_pack")
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def capture_executive_pack(self, user: User, *, period_label: Optional[str] = None) -> Dict[str, Any]:
        """Month-end bundle — all child snapshots are immutable executive records."""
        period_label = period_label or datetime.now(timezone.utc).strftime("%Y-%m")
        types = [
            ("spend_trends", {"quarters": 1}),
            ("vendor_breakdown", {"months": 1}),
            ("department_analysis", {"months": 3}),
            ("policy_violations", {"months": 3}),
            ("approval_health", {}),
        ]
        ids = []
        for stype, kwargs in types:
            row = self.capture(
                user,
                stype,
                period_label=period_label,
                months=kwargs.get("months", 3),
                quarters=kwargs.get("quarters", 1),
                immutable=True,
                executive=True,
            )
            ids.append(row.id)
        return {
            "period_label": period_label,
            "snapshot_ids": ids,
            "count": len(ids),
            "immutable": True,
        }

    def get_snapshot(
        self,
        tenant_id: int,
        snapshot_id: int,
        *,
        include_payload: bool = True,
    ) -> Dict[str, Any]:
        row = ImmutableSnapshotGuard.get_verified(self._db, snapshot_id, tenant_id)
        if not row:
            raise ValueError("Snapshot not found")
        out: Dict[str, Any] = {
            "id": row.id,
            "snapshot_type": row.snapshot_type,
            "period_label": row.period_label,
            "department": row.department,
            "summary_text": row.summary_text,
            "immutable": row.immutable,
            "is_executive": row.is_executive,
            "content_hash": row.content_hash,
            "frozen_at": row.frozen_at,
            "created_at": row.created_at,
            "integrity_verified": verify_snapshot_integrity(row) if row.immutable else None,
        }
        if include_payload:
            out["payload"] = row.payload
        return out

    def list_snapshots(
        self,
        tenant_id: int,
        *,
        snapshot_type: Optional[str] = None,
        executive_only: bool = False,
        limit: int = 50,
    ) -> List[AnalyticsSnapshot]:
        q = self._db.query(AnalyticsSnapshot).filter(
            AnalyticsSnapshot.tenant_id == tenant_id
        )
        if snapshot_type:
            q = q.filter(AnalyticsSnapshot.snapshot_type == snapshot_type)
        if executive_only:
            q = q.filter(AnalyticsSnapshot.is_executive.is_(True))
        return q.order_by(AnalyticsSnapshot.created_at.desc()).limit(limit).all()

    def compare(
        self,
        tenant_id: int,
        snapshot_id_a: int,
        snapshot_id_b: int,
    ) -> Dict[str, Any]:
        a = ImmutableSnapshotGuard.get_verified(self._db, snapshot_id_a, tenant_id)
        b = ImmutableSnapshotGuard.get_verified(self._db, snapshot_id_b, tenant_id)
        if not a or not b:
            raise ValueError("Snapshot not found")

        total_a = self._extract_total(a.payload)
        total_b = self._extract_total(b.payload)
        change_pct = None
        if total_a and total_b and total_a > 0:
            change_pct = round((total_b - total_a) / total_a * 100, 1)

        return {
            "snapshot_a": {
                "id": a.id,
                "period": a.period_label,
                "type": a.snapshot_type,
                "total": total_a,
                "content_hash": a.content_hash,
            },
            "snapshot_b": {
                "id": b.id,
                "period": b.period_label,
                "type": b.snapshot_type,
                "total": total_b,
                "content_hash": b.content_hash,
            },
            "change_pct": change_pct,
            "both_immutable": bool(a.immutable and b.immutable),
            "narrative": (
                f"Spend changed {change_pct:+.1f}% between {a.period_label} and {b.period_label}."
                if change_pct is not None
                else "Unable to compare totals between snapshots."
            ),
        }

    def _build_payload(
        self,
        user: User,
        snapshot_type: str,
        *,
        department: Optional[str],
        months: int,
        quarters: int,
    ) -> Dict[str, Any]:
        tenant_id = resolve_tenant_id(user)
        if snapshot_type == "spend_trends":
            return self._facade.spend_trends(user, tenant_id, quarters=quarters, department=department)
        if snapshot_type == "vendor_breakdown":
            return self._facade.top_vendors(user, tenant_id, limit=15, months=months)
        if snapshot_type == "department_analysis":
            return self._facade.department_analysis(user, tenant_id, months=months)
        if snapshot_type == "category_breakdown":
            return self._facade.category_breakdown(
                user, tenant_id, months=months, department=department
            )
        if snapshot_type == "policy_violations":
            return self._facade.policy_violations(user, tenant_id, months=months)
        if snapshot_type == "approval_health":
            return self._facade.approval_health(user, tenant_id)
        if snapshot_type == "forecast":
            return self._facade.forecast(user, tenant_id, lookback_months=months, department=department)
        raise ValueError(f"Unknown snapshot type: {snapshot_type}")

    def _extract_total(self, payload: Dict[str, Any]) -> Optional[float]:
        for key in ("total_spend", "total", "current_quarter_spend"):
            if key in payload and payload[key] is not None:
                return float(payload[key])
        return None
