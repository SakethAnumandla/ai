"""Partitioned context window for LLM consistency."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.ai.schemas.tool_result import ToolResult


@dataclass
class ContextPartition:
    """Structured sections sent as separate system blocks."""

    system: str
    summary: Optional[str] = None
    active_workflow: Optional[str] = None
    user_preferences: Optional[str] = None
    workflow_memory: Optional[str] = None
    reference_resolution: Optional[str] = None
    memory_explanations: Optional[str] = None
    recent_messages: List[Dict[str, str]] = field(default_factory=list)
    tool_outputs: Optional[str] = None

    def to_openai_messages(self) -> List[Dict[str, Any]]:
        """Convert partitions to OpenAI message list."""
        messages: List[Dict[str, Any]] = []

        messages.append({
            "role": "system",
            "content": f"[SYSTEM]\n{self.system}",
        })

        if self.summary:
            messages.append({
                "role": "system",
                "content": f"[SESSION SUMMARY]\n{self.summary}",
            })

        if self.active_workflow:
            messages.append({
                "role": "system",
                "content": f"[ACTIVE WORKFLOW]\n{self.active_workflow}",
            })

        if self.user_preferences:
            messages.append({
                "role": "system",
                "content": f"[USER PREFERENCES]\n{self.user_preferences}",
            })

        if self.workflow_memory:
            messages.append({
                "role": "system",
                "content": f"[WORKFLOW MEMORY]\n{self.workflow_memory}",
            })

        if self.reference_resolution:
            messages.append({
                "role": "system",
                "content": f"[RESOLVED REFERENCES]\n{self.reference_resolution}",
            })

        if self.memory_explanations:
            messages.append({
                "role": "system",
                "content": f"[MEMORY RATIONALE]\n{self.memory_explanations}",
            })

        for msg in self.recent_messages:
            messages.append(msg)

        if self.tool_outputs:
            messages.append({
                "role": "system",
                "content": f"[TOOL OUTPUTS — factual ground truth]\n{self.tool_outputs}",
            })

        return messages


def build_active_workflow_section(
    *,
    pending_confirmation_summary: Optional[str] = None,
    draft_expense_hint: Optional[str] = None,
    pending_intent: Optional[str] = None,
) -> Optional[str]:
    parts = []
    if pending_confirmation_summary:
        parts.append(f"Awaiting user confirmation: {pending_confirmation_summary}")
    if draft_expense_hint:
        parts.append(f"Draft in progress: {draft_expense_hint}")
    if pending_intent:
        parts.append(f"Pending intent: {pending_intent}")
    if not parts:
        return None
    return "\n".join(parts)


def format_tool_outputs_section(tool_results: List[ToolResult]) -> Optional[str]:
    if not tool_results:
        return None
    lines = []
    for i, r in enumerate(tool_results, 1):
        status = "ok" if r.success else "failed"
        lines.append(f"{i}. [{status}] {r.message}")
        if r.data:
            lines.append(f"   data: {r.data}")
    return "\n".join(lines)
