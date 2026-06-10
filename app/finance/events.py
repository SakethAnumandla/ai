"""SQLAlchemy hooks — block mutation of immutable analytics snapshots."""
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.finance.models import AnalyticsSnapshot
from app.finance.snapshot_immutability import ImmutableSnapshotError


@event.listens_for(AnalyticsSnapshot, "before_update")
def _block_immutable_snapshot_update(mapper, connection, target: AnalyticsSnapshot):
    if not target.immutable:
        return
    # Block changes to frozen analytical content
    state = Session.object_state(target)
    if not state.modified:
        return
    for attr in state.attrs:
        if not attr.history.has_changes():
            continue
        key = attr.key
        if key in ("payload", "summary_text", "period_label", "snapshot_type", "content_hash"):
            raise ImmutableSnapshotError(
                f"Snapshot {target.id} is immutable; cannot update '{key}'."
            )


@event.listens_for(AnalyticsSnapshot, "before_delete")
def _block_immutable_snapshot_delete(mapper, connection, target: AnalyticsSnapshot):
    if target.immutable:
        raise ImmutableSnapshotError(
            f"Snapshot {target.id} is immutable and cannot be deleted."
        )
