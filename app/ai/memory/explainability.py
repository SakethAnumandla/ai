"""Memory explainability and confidence visibility for APIs."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.ai.memory.explanations import MemoryExplanationBuilder
from app.ai.memory.policy import EffectiveMemoryPolicy, MemoryPolicyService
from app.ai.memory.repository import AIRepository
from app.ai.models.entities import MemoryType
from app.ai.schemas.common import TenantUserContext
from app.ai.schemas.memory_governance import (
    ConfidenceCandidateOut,
    MemoryConfidenceItem,
    MemoryConfidenceResponse,
    MemoryExplanationItem,
    MemoryExplanationsResponse,
    TenantMemoryPolicyOut,
)

_PREF_VENDOR_PREFIX = "preference:vendor:"
_PREF_PAYMENT = "preference:payment_method"
_PREF_CATEGORY = "preference:category"


class MemoryExplainabilityService:
    def __init__(self, repository: AIRepository, policy_service: MemoryPolicyService):
        self._repo = repository
        self._policy = policy_service
        self._explainer = MemoryExplanationBuilder()

    def _policy_out(self, effective: EffectiveMemoryPolicy) -> TenantMemoryPolicyOut:
        row = self._policy.get_or_create_row(effective.tenant_id)
        return TenantMemoryPolicyOut(
            tenant_id=effective.tenant_id,
            allow_preference_learning=effective.allow_preference_learning,
            allow_behavioral_memory=effective.allow_behavioral_memory,
            allow_long_term_storage=effective.allow_long_term_storage,
            allow_entity_graph=effective.allow_entity_graph,
            allow_anomaly_detection=effective.allow_anomaly_detection,
            updated_at=row.updated_at,
        )

    def get_explanations(self, ctx: TenantUserContext) -> MemoryExplanationsResponse:
        effective = self._policy.get_effective(ctx.tenant_id)
        items: List[MemoryExplanationItem] = []

        if not effective.can_learn_preferences():
            return MemoryExplanationsResponse(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                explanations=[],
                policy=self._policy_out(effective),
                generated_at=datetime.now(timezone.utc),
            )

        rows = self._repo.fetch_memories_by_type(
            ctx, MemoryType.PREFERENCE.value, limit=50
        )
        for row in rows:
            val = row.value or {}
            if row.memory_key == _PREF_PAYMENT:
                expl = self._explainer.payment_method(val)
                candidates = val.get("candidates") or {}
                items.append(
                    MemoryExplanationItem(
                        field="payment_method",
                        memory_key=row.memory_key,
                        text=expl.format_user_facing() if expl else "No explanation available.",
                        confidence=float(val.get("primary_confidence", 0)),
                        evidence_count=int(val.get("count", 0)),
                        tentative=bool(val.get("tentative")),
                        candidates=candidates,
                    )
                )
            elif row.memory_key.startswith(_PREF_VENDOR_PREFIX):
                expl = self._explainer.vendor(val)
                if expl:
                    items.append(
                        MemoryExplanationItem(
                            field="vendor_name",
                            memory_key=row.memory_key,
                            text=expl.format_user_facing(),
                            confidence=float(val.get("confidence", 0)),
                            evidence_count=int(val.get("count", 0)),
                            candidates={},
                        )
                    )
            elif row.memory_key == _PREF_CATEGORY:
                cat = val.get("main_category", "")
                items.append(
                    MemoryExplanationItem(
                        field="main_category",
                        memory_key=row.memory_key,
                        text=f"Common category: {cat.replace('_', ' ')}.",
                        confidence=float(val.get("confidence", row.importance or 0)),
                        evidence_count=int(val.get("count", 0)),
                        candidates={},
                    )
                )

        return MemoryExplanationsResponse(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            explanations=items,
            policy=self._policy_out(effective),
            generated_at=datetime.now(timezone.utc),
        )

    def get_confidence_report(self, ctx: TenantUserContext) -> MemoryConfidenceResponse:
        effective = self._policy.get_effective(ctx.tenant_id)
        items: List[MemoryConfidenceItem] = []

        rows = self._repo.fetch_memories(ctx, limit=80)
        for row in rows:
            if row.memory_type not in (MemoryType.PREFERENCE.value, MemoryType.GRAPH.value):
                continue
            val = row.value or {}
            candidates_out: List[ConfidenceCandidateOut] = []
            raw_candidates = val.get("candidates") or {}
            if isinstance(raw_candidates, dict):
                for ck, cv in raw_candidates.items():
                    if isinstance(cv, dict):
                        candidates_out.append(
                            ConfidenceCandidateOut(
                                value=str(ck),
                                confidence=float(cv.get("confidence", 0)),
                                weighted_count=float(cv.get("weighted_count", 0)),
                                count=int(cv.get("count", 0)),
                                last_used_at=cv.get("last_used_at"),
                            )
                        )
                candidates_out.sort(key=lambda c: c.confidence, reverse=True)

            primary = val.get("payment_method") or val.get("vendor_name") or val.get("main_category")
            items.append(
                MemoryConfidenceItem(
                    memory_key=row.memory_key,
                    memory_type=row.memory_type,
                    primary_value=str(primary) if primary else None,
                    primary_confidence=float(
                        val.get("primary_confidence", val.get("confidence", row.importance or 0))
                    ),
                    importance=float(row.importance or 0),
                    tentative=bool(val.get("tentative")),
                    candidates=candidates_out,
                    evolved_at=val.get("evolved_at"),
                )
            )

        return MemoryConfidenceResponse(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            items=items,
            policy=self._policy_out(effective),
        )
