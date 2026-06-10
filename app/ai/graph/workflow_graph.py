"""Lightweight workflow entity graph — structured links, no vector DB."""
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.ai.memory.repository import AIRepository

if TYPE_CHECKING:
    from app.ai.memory.policy import MemoryPolicyService
from app.ai.memory.importance import MemoryImportanceScorer
from app.ai.models.entities import MemoryType
from app.ai.schemas.common import TenantUserContext
from app.ai.schemas.memory import MemoryEntryCreate
from app.models import Expense


def _graph_key(expense_id: int) -> str:
    return f"graph:expense:{expense_id}"


class WorkflowEntityGraph:
    """
    expense ↔ vendor ↔ payment_method ↔ category ↔ workflow_state
    Stored as JSON in Redis long-term memory (hash ``ai:ltm:{tenant}:{user}``).
    """

    def __init__(
        self,
        repository: AIRepository,
        policy: Optional["MemoryPolicyService"] = None,
    ):
        self._repo = repository
        self._scorer = MemoryImportanceScorer()
        self._policy = policy

    def link_expense(self, ctx: TenantUserContext, expense: Expense, *, workflow_state: str = "draft") -> None:
        if self._policy is not None:
            if not self._policy.get_effective(ctx.tenant_id).can_write_graph():
                return
        node = {
            "expense_id": expense.id,
            "vendor_name": expense.vendor_name,
            "payment_method": expense.payment_method.value if expense.payment_method else None,
            "main_category": expense.main_category.value if expense.main_category else None,
            "sub_category": expense.sub_category,
            "workflow_state": workflow_state,
            "bill_name": expense.bill_name,
            "bill_amount": expense.bill_amount,
        }
        existing = self.get_expense_node(ctx, expense.id)
        usage = int((existing or {}).get("usage_count", 0)) + 1
        node["usage_count"] = usage

        self._repo.save_memory(
            ctx,
            MemoryEntryCreate(
                memory_type=MemoryType.GRAPH,
                memory_key=_graph_key(expense.id),
                value=node,
                importance=self._scorer.score_graph_link(usage_count=usage),
            ),
        )

        if expense.vendor_name:
            self._repo.save_memory(
                ctx,
                MemoryEntryCreate(
                    memory_type=MemoryType.GRAPH,
                    memory_key=f"graph:vendor:{expense.vendor_name.strip().lower()}",
                    value={"vendor_name": expense.vendor_name, "last_expense_id": expense.id},
                    importance=0.65,
                ),
            )

    def get_expense_node(self, ctx: TenantUserContext, expense_id: int) -> Optional[Dict[str, Any]]:
        rows = self._repo.fetch_memories(ctx, limit=80)
        key = _graph_key(expense_id)
        for row in rows:
            if row.memory_key == key:
                return row.value
        return None

    def resolve_vendor_last_expense(self, ctx: TenantUserContext, vendor_name: str) -> Optional[Dict[str, Any]]:
        key = f"graph:vendor:{vendor_name.strip().lower()}"
        rows = self._repo.fetch_memories(ctx, limit=80)
        for row in rows:
            if row.memory_key == key:
                eid = (row.value or {}).get("last_expense_id")
                if eid:
                    return self.get_expense_node(ctx, int(eid))
        return None

    def context_lines(self, ctx: TenantUserContext, limit: int = 5) -> List[str]:
        rows = self._repo.fetch_memories_by_type(ctx, MemoryType.GRAPH.value, limit=limit)
        lines = []
        for row in rows:
            if not row.memory_key.startswith("graph:expense:"):
                continue
            v = row.value or {}
            parts = [f"Expense #{v.get('expense_id')}"]
            if v.get("vendor_name"):
                parts.append(f"vendor={v['vendor_name']}")
            if v.get("payment_method"):
                parts.append(f"payment={v['payment_method']}")
            if v.get("main_category"):
                parts.append(f"category={v['main_category']}")
            lines.append(" — ".join(parts))
        return lines[:limit]
