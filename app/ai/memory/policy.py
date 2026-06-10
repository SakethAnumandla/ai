"""Tenant memory sandboxing — enterprise policies (PostgreSQL)."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.models.entities import AITenantMemoryPolicy


@dataclass(frozen=True)
class EffectiveMemoryPolicy:
    tenant_id: int
    allow_preference_learning: bool = True
    allow_behavioral_memory: bool = True
    allow_long_term_storage: bool = True
    allow_entity_graph: bool = True
    allow_anomaly_detection: bool = True

    def can_learn_preferences(self) -> bool:
        return self.allow_preference_learning and self.allow_behavioral_memory

    def can_persist_long_term(self) -> bool:
        return self.allow_long_term_storage

    def can_write_graph(self) -> bool:
        return self.allow_entity_graph and self.allow_long_term_storage

    def can_run_anomaly_detection(self) -> bool:
        return self.allow_anomaly_detection


class MemoryPolicyService:
    """Resolve and update per-tenant memory sandbox rules."""

    def __init__(self, db: Session):
        self._db = db

    def get_effective(self, tenant_id: int) -> EffectiveMemoryPolicy:
        row = (
            self._db.query(AITenantMemoryPolicy)
            .filter(AITenantMemoryPolicy.tenant_id == tenant_id)
            .first()
        )
        if not row:
            return EffectiveMemoryPolicy(tenant_id=tenant_id)
        return EffectiveMemoryPolicy(
            tenant_id=tenant_id,
            allow_preference_learning=bool(row.allow_preference_learning),
            allow_behavioral_memory=bool(row.allow_behavioral_memory),
            allow_long_term_storage=bool(row.allow_long_term_storage),
            allow_entity_graph=bool(row.allow_entity_graph),
            allow_anomaly_detection=bool(row.allow_anomaly_detection),
        )

    def get_or_create_row(self, tenant_id: int) -> AITenantMemoryPolicy:
        row = (
            self._db.query(AITenantMemoryPolicy)
            .filter(AITenantMemoryPolicy.tenant_id == tenant_id)
            .first()
        )
        if row:
            return row
        row = AITenantMemoryPolicy(tenant_id=tenant_id)
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def update_policy(
        self,
        tenant_id: int,
        *,
        allow_preference_learning: Optional[bool] = None,
        allow_behavioral_memory: Optional[bool] = None,
        allow_long_term_storage: Optional[bool] = None,
        allow_entity_graph: Optional[bool] = None,
        allow_anomaly_detection: Optional[bool] = None,
    ) -> AITenantMemoryPolicy:
        row = self.get_or_create_row(tenant_id)
        if allow_preference_learning is not None:
            row.allow_preference_learning = allow_preference_learning
        if allow_behavioral_memory is not None:
            row.allow_behavioral_memory = allow_behavioral_memory
        if allow_long_term_storage is not None:
            row.allow_long_term_storage = allow_long_term_storage
        if allow_entity_graph is not None:
            row.allow_entity_graph = allow_entity_graph
        if allow_anomaly_detection is not None:
            row.allow_anomaly_detection = allow_anomaly_detection
        row.updated_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(row)
        return row
