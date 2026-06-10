"""Workflow-specific memory scoping — expense vs approval vs reimbursement."""
import re
from typing import List, Optional

from app.ai.orchestrator.intent import UserIntent
from app.ai.schemas.conversation import ConversationMessageOut
from app.ai.schemas.workflow import WorkflowScope

_SCOPE_KEYWORDS = {
    WorkflowScope.EXPENSE: (
        "expense", "bill", "receipt", "draft", "vendor", "merchant", "lunch", "travel", "uber",
    ),
    WorkflowScope.APPROVAL: (
        "approve", "reject", "pending approval", "claim", "review",
    ),
    WorkflowScope.REIMBURSEMENT: (
        "reimburse", "reimbursement", "payout", "wallet",
    ),
    WorkflowScope.ANALYTICS: (
        "spend", "analytics", "report", "breakdown", "vendor spend",
    ),
}


class ContextScopeFilter:
    """Prevent expense workflow context from polluting approval workflows."""

    def detect_scope(
        self,
        user_query: str,
        *,
        intent: Optional[UserIntent] = None,
        active_scope: Optional[WorkflowScope] = None,
    ) -> WorkflowScope:
        if active_scope and active_scope != WorkflowScope.GENERAL:
            return active_scope

        if intent == UserIntent.APPROVE or intent == UserIntent.LIST_PENDING:
            return WorkflowScope.APPROVAL
        if intent == UserIntent.CREATE_EXPENSE or intent == UserIntent.SUBMIT_EXPENSE:
            return WorkflowScope.EXPENSE
        if intent == UserIntent.ANALYTICS:
            return WorkflowScope.ANALYTICS

        lowered = user_query.lower()
        scores = {scope: 0 for scope in WorkflowScope if scope != WorkflowScope.GENERAL}
        for scope, keywords in _SCOPE_KEYWORDS.items():
            for kw in keywords:
                if kw in lowered:
                    scores[scope] += 1

        best = max(scores.items(), key=lambda x: x[1])
        if best[1] > 0:
            return best[0]
        return WorkflowScope.GENERAL

    def filter_messages(
        self,
        messages: List[ConversationMessageOut],
        scope: WorkflowScope,
    ) -> List[ConversationMessageOut]:
        if scope == WorkflowScope.GENERAL:
            return messages

        keywords = _SCOPE_KEYWORDS.get(scope, ())
        general_kw = ("hello", "hi", "thanks", "help")

        filtered: List[ConversationMessageOut] = []
        for msg in messages:
            text = (msg.content or "").lower()
            if any(g in text for g in general_kw):
                filtered.append(msg)
                continue
            if scope == WorkflowScope.EXPENSE and any(k in text for k in keywords):
                filtered.append(msg)
            elif scope != WorkflowScope.EXPENSE and any(k in text for k in keywords):
                filtered.append(msg)

        return filtered if len(filtered) >= 2 else messages

    def filter_memory_lines(self, lines: List[str], scope: WorkflowScope) -> List[str]:
        if scope == WorkflowScope.GENERAL:
            return lines
        keywords = _SCOPE_KEYWORDS.get(scope, ())
        return [ln for ln in lines if any(k in ln.lower() for k in keywords)] or lines
