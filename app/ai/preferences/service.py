"""Persistent user preference memory with conflict resolution, sandboxing, and audit."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.ai.memory.audit import MemoryAuditService
from app.ai.memory.conflict_resolver import PreferenceConflictResolver
from app.ai.memory.explanations import MemoryExplanationBuilder
from app.ai.memory.importance import MemoryImportanceScorer
from app.ai.memory.noise_suppression import MemoryNoiseFilter
from app.ai.memory.policy import MemoryPolicyService
from app.ai.memory.repository import AIRepository
from app.ai.models.entities import MemoryType
from app.ai.schemas.common import TenantUserContext
from app.ai.schemas.memory import MemoryEntryCreate
from app.ai.schemas.memory_intelligence import PreferenceSuggestion
from app.models import Expense

_PREF_VENDOR_PREFIX = "preference:vendor:"
_PREF_PAYMENT = "preference:payment_method"
_PREF_CATEGORY = "preference:category"
_PREF_PREFERRED_NAME = "preference:preferred_name"


class UserPreferenceService:
    def __init__(
        self,
        db: Session,
        repository: AIRepository,
        *,
        policy: Optional[MemoryPolicyService] = None,
        audit: Optional[MemoryAuditService] = None,
    ):
        self._db = db
        self._repo = repository
        self._policy = policy or MemoryPolicyService(db)
        self._audit = audit or MemoryAuditService(db)
        self._scorer = MemoryImportanceScorer()
        self._noise = MemoryNoiseFilter()
        self._conflicts = PreferenceConflictResolver()
        self._explanations = MemoryExplanationBuilder()

    def learn_from_expense(
        self,
        ctx: TenantUserContext,
        expense: Expense,
        *,
        source: str = "expense.record",
    ) -> bool:
        """Returns False if blocked by tenant memory policy."""
        effective = self._policy.get_effective(ctx.tenant_id)
        if not effective.can_learn_preferences():
            self._audit.record(
                ctx,
                memory_key=_PREF_PAYMENT,
                change_type="blocked_by_policy",
                source=source,
                evidence={"expense_id": expense.id, "reason": "preference_learning_disabled"},
            )
            return False
        if not effective.can_persist_long_term():
            return False

        if expense.vendor_name:
            ok, weight = self._noise.observation_weight(expense, "vendor_name")
            if ok:
                key = f"{_PREF_VENDOR_PREFIX}{expense.vendor_name.strip().lower()}"
                self._learn_vendor(ctx, key, expense.vendor_name, weight, source=source, expense_id=expense.id)

        if expense.payment_method:
            ok, weight = self._noise.observation_weight(expense, "payment_method")
            if ok:
                cat = expense.main_category.value if expense.main_category else None
                self._learn_payment(
                    ctx,
                    expense.payment_method.value,
                    weight,
                    category=cat,
                    source=source,
                    expense_id=expense.id,
                )

        if expense.main_category:
            ok, weight = self._noise.observation_weight(expense, "main_category")
            if ok:
                self._bump_simple(
                    ctx,
                    _PREF_CATEGORY,
                    {"main_category": expense.main_category.value, "weighted_count": weight},
                    source=source,
                    expense_id=expense.id,
                )
        return True

    def _learn_vendor(
        self,
        ctx: TenantUserContext,
        key: str,
        vendor_name: str,
        weight: float,
        *,
        source: str,
        expense_id: int,
    ) -> None:
        before = self._load_value(ctx, key)
        store = dict(before) if before else {"vendor_name": vendor_name}
        conf_before = float(store.get("confidence", 0))
        resolution = self._conflicts.resolve_vendor_conflict(store, vendor_name, weight)
        store["vendor_name"] = vendor_name
        store["confidence"] = self._noise.cap_confidence_from_sparse_data(
            resolution.primary_confidence,
            float(store.get("weighted_count", 0)),
        )
        self._persist(ctx, key, store, resolution.primary_confidence)
        self._audit.record(
            ctx,
            memory_key=key,
            change_type="learned",
            source=source,
            before=before,
            after=store,
            evidence={"expense_id": expense_id, "vendor_name": vendor_name, "weight": weight},
            confidence_before=conf_before,
            confidence_after=store["confidence"],
        )

    def _learn_payment(
        self,
        ctx: TenantUserContext,
        method: str,
        weight: float,
        *,
        category: Optional[str] = None,
        source: str,
        expense_id: int,
    ) -> None:
        before = self._load_value(ctx, _PREF_PAYMENT)
        store = dict(before) if before else {"candidates": {}}
        conf_before = float(store.get("primary_confidence", 0))
        primary_before = store.get("payment_method")
        resolution = self._conflicts.resolve_payment_conflict(
            store, method, category=category, observation_weight=weight
        )
        wc = float((store.get("candidates") or {}).get(method, {}).get("weighted_count", 0))
        conf = self._noise.cap_confidence_from_sparse_data(resolution.primary_confidence, wc)
        store["primary_confidence"] = conf
        if not self._noise.can_promote_to_primary(wc) and store.get("payment_method") == method:
            store["tentative"] = True
        else:
            store.pop("tentative", None)

        change_type = "evolved" if resolution.evolved else "learned"
        if resolution.decayed_values:
            change_type = "conflict_resolved"

        self._persist(ctx, _PREF_PAYMENT, store, conf)
        self._audit.record(
            ctx,
            memory_key=_PREF_PAYMENT,
            change_type=change_type,
            source=source,
            before=before,
            after=store,
            evidence={
                "expense_id": expense_id,
                "payment_method": method,
                "category": category,
                "weight": weight,
                "decayed": resolution.decayed_values,
                "primary_before": primary_before,
            },
            confidence_before=conf_before,
            confidence_after=conf,
        )

    def _bump_simple(
        self,
        ctx: TenantUserContext,
        key: str,
        delta: Dict[str, Any],
        *,
        source: str,
        expense_id: int,
    ) -> None:
        before = self._load_value(ctx, key)
        store = dict(before) if before else {}
        conf_before = float(store.get("confidence", 0))
        wc = float(store.get("weighted_count", 0)) + float(delta.get("weighted_count", 1))
        store.update(delta)
        store["weighted_count"] = wc
        store["count"] = int(store.get("count", 0)) + 1
        store["last_used_at"] = datetime.now(timezone.utc).isoformat()
        conf = self._noise.cap_confidence_from_sparse_data(
            self._scorer.score_preference(count=int(wc), recurring=True),
            wc,
        )
        self._persist(ctx, key, store, conf)
        self._audit.record(
            ctx,
            memory_key=key,
            change_type="learned",
            source=source,
            before=before,
            after=store,
            evidence={"expense_id": expense_id, **delta},
            confidence_before=conf_before,
            confidence_after=conf,
        )

    def _load_value(self, ctx: TenantUserContext, key: str) -> Optional[Dict[str, Any]]:
        rows = self._repo.fetch_memories(ctx, limit=100)
        for row in rows:
            if row.memory_key == key:
                return dict(row.value or {})
        return None

    def _persist(
        self, ctx: TenantUserContext, key: str, value: Dict[str, Any], importance: float
    ) -> None:
        self._repo.save_memory(
            ctx,
            MemoryEntryCreate(
                memory_type=MemoryType.PREFERENCE,
                memory_key=key,
                value=value,
                importance=importance,
            ),
        )

    def set_preferred_name(self, ctx: TenantUserContext, name: str, *, source: str = "conversation") -> None:
        name = (name or "").strip()
        if len(name) < 2:
            return
        before = self._load_value(ctx, _PREF_PREFERRED_NAME)
        store = {"name": name, "source": source}
        self._persist(ctx, _PREF_PREFERRED_NAME, store, 1.0)
        self._audit.record(
            ctx,
            memory_key=_PREF_PREFERRED_NAME,
            change_type="learned",
            source=source,
            before=before,
            after=store,
            evidence={"name": name},
        )

    def get_preferred_name(self, ctx: TenantUserContext) -> Optional[str]:
        val = self._load_value(ctx, _PREF_PREFERRED_NAME)
        if val and val.get("name"):
            name = str(val["name"])
            logger.info(
                "Loaded preferred_name=%s user_id=%s tenant_id=%s",
                name,
                ctx.user_id,
                ctx.tenant_id,
            )
            return name
        return None

    def get_preferences_summary(self, ctx: TenantUserContext) -> List[str]:
        if not self._policy.get_effective(ctx.tenant_id).can_learn_preferences():
            return []
        rows = self._repo.fetch_memories_by_type(
            ctx, MemoryType.PREFERENCE.value, limit=40
        )
        lines: List[str] = []
        vendors: List[tuple] = []
        payment_store: Optional[Dict[str, Any]] = None
        category: Optional[str] = None

        # preferred_name is NOT injected into the LLM system context — it caused
        # wrong-name hallucinations (e.g. "Hello, Varun") when stale memory existed.
        # Names are used only in the conversational fast-path after explicit intro.

        for row in rows:
            val = row.value or {}
            if row.memory_key.startswith(_PREF_VENDOR_PREFIX):
                wc = float(val.get("weighted_count", val.get("count", 0)))
                if self._noise.can_surface_in_prompt(wc, float(val.get("confidence", 0))):
                    vendors.append((val.get("vendor_name", ""), int(val.get("count", 0))))
            elif row.memory_key == _PREF_PAYMENT:
                payment_store = val
            elif row.memory_key == _PREF_CATEGORY:
                category = val.get("main_category")

        vendors.sort(key=lambda x: x[1], reverse=True)
        if vendors[:3]:
            names = ", ".join(v[0] for v in vendors[:3] if v[0])
            lines.append(f"Frequent vendors: {names}.")

        if payment_store and not payment_store.get("tentative"):
            method = payment_store.get("payment_method")
            candidates = payment_store.get("candidates") or {}
            entry = candidates.get(method, {}) if method else {}
            wc = float(entry.get("weighted_count", 0))
            conf = float(payment_store.get("primary_confidence", 0))
            if method and self._noise.can_surface_in_prompt(wc, conf):
                expl = self._explanations.payment_method(payment_store)
                if expl:
                    lines.append(expl.format_user_facing())
                else:
                    lines.append(
                        f"Preferred payment method: {method.replace('_', ' ')}."
                    )

        if category:
            lines.append(f"Common category: {category.replace('_', ' ')}.")
        return lines

    def suggest_payment(
        self, ctx: TenantUserContext, *, category: Optional[str] = None
    ) -> Optional[PreferenceSuggestion]:
        if not self._policy.get_effective(ctx.tenant_id).can_learn_preferences():
            return None
        store = self._load_value(ctx, _PREF_PAYMENT)
        if not store or store.get("tentative"):
            return None

        method = store.get("payment_method")
        if not method:
            return None

        candidates = store.get("candidates") or {}
        entry = candidates.get(method, {})
        wc = float(entry.get("weighted_count", 0))
        conf = float(store.get("primary_confidence", entry.get("confidence", 0)))

        if not self._noise.can_surface_in_prompt(wc, conf):
            return None

        label = method.replace("_", " ").upper() if method == "upi" else method.replace("_", " ")
        if category and "travel" in category.lower():
            prompt = f"Was this paid through {label} like your previous travel claims?"
        else:
            prompt = f"Was this paid through {label} like last time?"

        expl = self._explanations.payment_method(store, category=category)
        if expl and expl.superseded:
            prompt = (
                f"Was this paid through {label}? "
                f"(Your usual method was {expl.superseded.replace('_', ' ')}; "
                f"recent claims suggest {label}.)"
            )

        return PreferenceSuggestion(
            prompt=prompt,
            explanation=expl,
            value=method,
            confidence=conf,
        )

    def suggest_payment_prompt(self, ctx: TenantUserContext, *, category: Optional[str] = None) -> Optional[str]:
        suggestion = self.suggest_payment(ctx, category=category)
        if not suggestion:
            return None
        return self._explanations.append_to_prompt(suggestion.prompt, suggestion.explanation)

    def infer_payment_from_history(self, ctx: TenantUserContext, user_id: int) -> Optional[str]:
        store = self._load_value(ctx, _PREF_PAYMENT)
        if store and not store.get("tentative"):
            method = store.get("payment_method")
            candidates = store.get("candidates") or {}
            entry = candidates.get(method, {}) if method else {}
            wc = float(entry.get("weighted_count", 0))
            if method and self._noise.can_promote_to_primary(wc):
                return method
        recent = (
            self._db.query(Expense)
            .filter(Expense.user_id == user_id, Expense.payment_method.isnot(None))
            .order_by(Expense.created_at.desc())
            .limit(5)
            .all()
        )
        if recent:
            return recent[0].payment_method.value
        return None
