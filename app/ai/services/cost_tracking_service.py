"""Tenant-level AI usage and cost aggregation."""
import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.ai.models.entities import TenantAIUsage
from app.ai.schemas.audit import TokenUsage
from app.config import settings

logger = logging.getLogger(__name__)


class CostTrackingService:
    def __init__(self, db: Session):
        self._db = db

    def _estimate_cost(self, usage: TokenUsage) -> float:
        prompt_cost = (usage.prompt_tokens / 1_000_000) * settings.ai_cost_per_1m_prompt_tokens
        completion_cost = (usage.completion_tokens / 1_000_000) * settings.ai_cost_per_1m_completion_tokens
        return round(prompt_cost + completion_cost, 6)

    def _get_or_create_row(self, tenant_id: int, usage_date: date) -> TenantAIUsage:
        day_start = datetime.combine(usage_date, datetime.min.time(), tzinfo=timezone.utc)
        row = (
            self._db.query(TenantAIUsage)
            .filter(
                TenantAIUsage.tenant_id == tenant_id,
                TenantAIUsage.usage_date == day_start,
            )
            .first()
        )
        if row:
            return row
        row = TenantAIUsage(tenant_id=tenant_id, usage_date=day_start)
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def record_chat_usage(self, *, tenant_id: int, usage: TokenUsage) -> None:
        row = self._get_or_create_row(tenant_id, date.today())
        row.prompt_tokens = (row.prompt_tokens or 0) + usage.prompt_tokens
        row.completion_tokens = (row.completion_tokens or 0) + usage.completion_tokens
        row.total_tokens = (row.total_tokens or 0) + usage.total_tokens
        row.estimated_cost_usd = (row.estimated_cost_usd or 0) + self._estimate_cost(usage)
        row.request_count = (row.request_count or 0) + 1
        row.updated_at = datetime.now(timezone.utc)
        self._db.commit()

    def record_tool_invocation(self, *, tenant_id: int) -> None:
        row = self._get_or_create_row(tenant_id, date.today())
        row.tool_invocation_count = (row.tool_invocation_count or 0) + 1
        row.updated_at = datetime.now(timezone.utc)
        self._db.commit()
