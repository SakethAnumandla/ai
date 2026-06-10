"""Load per-tenant model configuration from ai_model_config."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.ai.models.entities import AIModelConfig
from app.config import settings


class ModelConfigService:
    def __init__(self, db: Session):
        self._db = db

    def get_active_config(self, tenant_id: int) -> Optional[AIModelConfig]:
        return (
            self._db.query(AIModelConfig)
            .filter(AIModelConfig.tenant_id == tenant_id, AIModelConfig.active.is_(True))
            .order_by(AIModelConfig.updated_at.desc())
            .first()
        )

    def resolve_model_name(self, tenant_id: int) -> str:
        cfg = self.get_active_config(tenant_id)
        return cfg.model_name if cfg else settings.openai_primary_model

    def resolve_enabled_tools(self, tenant_id: int) -> List[str]:
        cfg = self.get_active_config(tenant_id)
        if cfg and cfg.enabled_tools:
            return list(cfg.enabled_tools)
        return []
