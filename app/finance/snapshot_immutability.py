"""Immutable executive snapshots — content hash + write guards."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.finance.models import AnalyticsSnapshot


class ImmutableSnapshotError(ValueError):
    """Raised when a frozen snapshot is mutated or deleted."""


def compute_content_hash(payload: Dict[str, Any]) -> str:
    """Deterministic SHA-256 over canonical JSON (stable for audit)."""
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def seal_snapshot(row: AnalyticsSnapshot, *, executive: bool = False) -> None:
    """Mark snapshot frozen at capture time; sets hash before persist."""
    row.immutable = True
    row.is_executive = executive or row.snapshot_type in (
        "executive_pack",
        "spend_trends",
        "vendor_breakdown",
        "department_analysis",
        "policy_violations",
        "approval_health",
    )
    row.content_hash = compute_content_hash(row.payload or {})
    row.frozen_at = datetime.now(timezone.utc)


def verify_snapshot_integrity(row: AnalyticsSnapshot) -> bool:
    if not row.content_hash:
        return False
    return row.content_hash == compute_content_hash(row.payload or {})


class ImmutableSnapshotGuard:
    """Service-layer enforcement; complements SQLAlchemy before_update/delete hooks."""

    IMMUTABLE_FIELDS = frozenset({"payload", "summary_text", "period_label", "snapshot_type"})

    @staticmethod
    def assert_mutable(row: AnalyticsSnapshot) -> None:
        if row.immutable:
            raise ImmutableSnapshotError(
                f"Snapshot {row.id} is immutable (frozen {row.frozen_at}). "
                "Create a new snapshot instead of mutating history."
            )

    @staticmethod
    def assert_update_allowed(row: AnalyticsSnapshot, values: Dict[str, Any]) -> None:
        if not row.immutable:
            return
        blocked = set(values.keys()) & ImmutableSnapshotGuard.IMMUTABLE_FIELDS
        if blocked:
            raise ImmutableSnapshotError(
                f"Cannot modify {sorted(blocked)} on immutable snapshot {row.id}."
            )

    @staticmethod
    def get_verified(db: Session, snapshot_id: int, tenant_id: int) -> Optional[AnalyticsSnapshot]:
        row = (
            db.query(AnalyticsSnapshot)
            .filter(
                AnalyticsSnapshot.id == snapshot_id,
                AnalyticsSnapshot.tenant_id == tenant_id,
            )
            .first()
        )
        if not row:
            return None
        if row.immutable and not verify_snapshot_integrity(row):
            raise ImmutableSnapshotError(
                f"Snapshot {row.id} failed integrity check — possible tampering."
            )
        return row
