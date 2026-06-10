"""Memory anomaly detection — payment shifts, vendor changes, reimbursement patterns."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.ai.memory.policy import MemoryPolicyService
from app.ai.schemas.common import TenantUserContext
from app.ai.schemas.memory_governance import MemoryAnomaliesResponse, MemoryAnomalyOut, TenantMemoryPolicyOut
from app.config import settings
from app.models import Expense, ExpenseStatus


class MemoryAnomalyDetector:
    """Lightweight behavioral anomaly signals for fraud/risk (no ML)."""

    def __init__(self, db: Session, policy_service: MemoryPolicyService):
        self._db = db
        self._policy = policy_service

    def _policy_out(self, tenant_id: int) -> TenantMemoryPolicyOut:
        eff = self._policy.get_effective(tenant_id)
        row = self._policy.get_or_create_row(tenant_id)
        return TenantMemoryPolicyOut(
            tenant_id=tenant_id,
            allow_preference_learning=eff.allow_preference_learning,
            allow_behavioral_memory=eff.allow_behavioral_memory,
            allow_long_term_storage=eff.allow_long_term_storage,
            allow_entity_graph=eff.allow_entity_graph,
            allow_anomaly_detection=eff.allow_anomaly_detection,
            updated_at=row.updated_at,
        )

    def detect(self, ctx: TenantUserContext, *, lookback_days: int = 90) -> MemoryAnomaliesResponse:
        effective = self._policy.get_effective(ctx.tenant_id)
        now = datetime.now(timezone.utc)
        empty = MemoryAnomaliesResponse(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            anomalies=[],
            policy=self._policy_out(ctx.tenant_id),
        )
        if not effective.can_run_anomaly_detection():
            return empty

        since = now - timedelta(days=lookback_days)
        expenses = (
            self._db.query(Expense)
            .filter(Expense.user_id == ctx.user_id, Expense.created_at >= since)
            .order_by(Expense.created_at.desc())
            .limit(200)
            .all()
        )
        if len(expenses) < 5:
            return empty

        anomalies: List[MemoryAnomalyOut] = []
        anomalies.extend(self._payment_method_shift(expenses, now))
        anomalies.extend(self._vendor_concentration_shift(expenses, now))
        anomalies.extend(self._reimbursement_pattern(expenses, now))

        return MemoryAnomaliesResponse(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            anomalies=anomalies,
            policy=self._policy_out(ctx.tenant_id),
        )

    def _payment_method_shift(self, expenses: List[Expense], now: datetime) -> List[MemoryAnomalyOut]:
        recent = [e for e in expenses[:10] if e.payment_method]
        older = [e for e in expenses[10:30] if e.payment_method]
        if len(recent) < 3 or len(older) < 3:
            return []

        recent_counts = Counter(e.payment_method.value for e in recent)
        older_counts = Counter(e.payment_method.value for e in older)
        recent_top = recent_counts.most_common(1)[0][0]
        older_top = older_counts.most_common(1)[0][0]

        if recent_top == older_top:
            return []

        recent_share = recent_counts[recent_top] / len(recent)
        if recent_share < 0.6:
            return []

        return [
            MemoryAnomalyOut(
                anomaly_type="payment_method_shift",
                severity="medium",
                description=(
                    f"Recent expenses predominantly use {recent_top.replace('_', ' ')} "
                    f"while your prior pattern was {older_top.replace('_', ' ')}."
                ),
                detected_at=now,
                context={
                    "recent_dominant": recent_top,
                    "historical_dominant": older_top,
                    "recent_sample_size": len(recent),
                },
            )
        ]

    def _vendor_concentration_shift(self, expenses: List[Expense], now: datetime) -> List[MemoryAnomalyOut]:
        with_vendor = [e for e in expenses if e.vendor_name]
        if len(with_vendor) < 8:
            return []

        recent_vendors = {e.vendor_name for e in with_vendor[:5]}
        new_vendors = [
            e for e in with_vendor[:8]
            if e.vendor_name and e.vendor_name not in {x.vendor_name for x in with_vendor[8:40]}
        ]
        if len(new_vendors) < 3:
            return []

        names = ", ".join(sorted({e.vendor_name for e in new_vendors[:3]})[:3])
        return [
            MemoryAnomalyOut(
                anomaly_type="new_vendor_cluster",
                severity="low",
                description=f"Multiple recent expenses use vendors not seen in your prior history: {names}.",
                detected_at=now,
                context={"new_vendor_count": len(new_vendors), "recent_vendors": list(recent_vendors)},
            )
        ]

    def _reimbursement_pattern(self, expenses: List[Expense], now: datetime) -> List[MemoryAnomalyOut]:
        high_amounts = [
            e for e in expenses[:20]
            if e.bill_amount and e.bill_amount >= settings.ai_high_amount_threshold * 0.5
        ]
        pending = [e for e in expenses if e.status == ExpenseStatus.PENDING]
        if len(high_amounts) >= 2 and len(pending) >= 3:
            return [
                MemoryAnomalyOut(
                    anomaly_type="elevated_submission_activity",
                    severity="medium",
                    description=(
                        f"You have {len(pending)} pending submissions including "
                        f"{len(high_amounts)} higher-value items in the lookback window."
                    ),
                    detected_at=now,
                    context={
                        "pending_count": len(pending),
                        "high_value_recent": len(high_amounts),
                    },
                )
            ]
        return []
