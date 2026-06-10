"""Build ranked, partitioned LLM context from memory + session state."""
from typing import Any, Dict, List, Optional, Union

from app.ai.memory.context_scope import ContextScopeFilter
from app.ai.memory.context_partition import (
    ContextPartition,
    build_active_workflow_section,
    format_tool_outputs_section,
)
from app.ai.memory.memory_ranker import MemoryRanker
from app.ai.memory.token_budget import TokenBudgetManager
from app.ai.schemas.conversation import RecentContextOut
from app.ai.schemas.tool_result import ToolResult
from app.ai.schemas.workflow import WorkflowScope
from app.config import settings


class ContextBuilder:
    def __init__(
        self,
        ranker: Optional[MemoryRanker] = None,
        token_budget: Optional[TokenBudgetManager] = None,
    ):
        self._ranker = ranker or MemoryRanker()
        self._token_budget = token_budget or TokenBudgetManager()
        self._scope_filter = ContextScopeFilter()

    def rank_context(
        self,
        context: RecentContextOut,
        *,
        user_query: str,
        has_pending_confirmation: bool = False,
        scope: WorkflowScope = WorkflowScope.GENERAL,
    ) -> RecentContextOut:
        messages = self._scope_filter.filter_messages(context.messages, scope)
        ranked = self._ranker.rank_messages(
            messages,
            user_query=user_query,
            has_pending_confirmation=has_pending_confirmation,
            limit=settings.ai_recent_message_limit,
        )
        return RecentContextOut(
            session_id=context.session_id,
            messages=ranked,
            summary=context.summary,
            compressed=context.compressed,
        )

    def build_partitioned_messages(
        self,
        *,
        system_prompt: str,
        context: RecentContextOut,
        tool_results: Optional[List[ToolResult]] = None,
        pending_confirmation_summary: Optional[str] = None,
        draft_hint: Optional[str] = None,
        preference_lines: Optional[List[str]] = None,
        workflow_lines: Optional[List[str]] = None,
        reference_context: Optional[str] = None,
        pending_intent_summary: Optional[str] = None,
        memory_explanations: Optional[List[str]] = None,
    ) -> List[dict]:
        workflow = build_active_workflow_section(
            pending_confirmation_summary=pending_confirmation_summary,
            draft_expense_hint=draft_hint,
            pending_intent=pending_intent_summary,
        )
        tool_section = format_tool_outputs_section(tool_results or [])
        prefs = "\n".join(preference_lines) if preference_lines else None
        wf_mem = "\n".join(workflow_lines) if workflow_lines else None
        expl = "\n".join(memory_explanations) if memory_explanations else None

        partition = ContextPartition(
            system=system_prompt,
            summary=context.summary,
            active_workflow=workflow,
            user_preferences=prefs,
            workflow_memory=wf_mem,
            reference_resolution=reference_context,
            memory_explanations=expl,
            recent_messages=[
                {"role": m.role, "content": m.content} for m in context.messages
            ],
            tool_outputs=tool_section,
        )
        messages = partition.to_openai_messages()
        trimmed, _ = self._token_budget.trim_messages(messages)
        return trimmed


def replace_last_user_message_content(
    messages: List[Dict[str, Any]],
    new_content: Union[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Swap the most recent user message body for multimodal OpenAI content.

    Used when the persisted user line is text-only but the live model turn
    should include images / PDF excerpts.
    """
    out: List[Dict[str, Any]] = [dict(m) for m in messages]
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            out[i]["content"] = new_content
            return out
    out.append({"role": "user", "content": new_content})
    return out
