"""Memory priority ranking — relevance beyond recency-only."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.ai.schemas.conversation import ConversationMessageOut

_WORKFLOW_KEYWORDS = (
    "submit", "approve", "reject", "confirm", "pending", "draft", "reimburse",
    "confirmation", "expense #", "claim #",
)
_IMPORTANCE_KEYWORDS = (
    "policy", "amount", "₹", "rs", "total", "vendor", "urgent", "deadline",
    "approval", "rejected", "approved",
)


@dataclass
class ScoredMessage:
    message: ConversationMessageOut
    score: float
    factors: Dict[str, float]


class MemoryRanker:
    """Score messages for context selection."""

    def __init__(
        self,
        *,
        recency_weight: float = 0.35,
        semantic_weight: float = 0.30,
        workflow_weight: float = 0.25,
        unresolved_weight: float = 0.10,
    ):
        self._w_recency = recency_weight
        self._w_semantic = semantic_weight
        self._w_workflow = workflow_weight
        self._w_unresolved = unresolved_weight

    def score_message(
        self,
        msg: ConversationMessageOut,
        *,
        index: int,
        total: int,
        user_query: Optional[str] = None,
        has_pending_confirmation: bool = False,
    ) -> ScoredMessage:
        content_lower = (msg.content or "").lower()
        now = datetime.now(timezone.utc)

        # Recency: newer messages score higher (0–1)
        recency = (index + 1) / max(total, 1)

        # Semantic overlap with current user query
        semantic = 0.0
        if user_query:
            q_tokens = set(user_query.lower().split())
            m_tokens = set(content_lower.split())
            if q_tokens:
                semantic = len(q_tokens & m_tokens) / len(q_tokens)

        # Workflow relevance
        workflow = 0.0
        if any(kw in content_lower for kw in _WORKFLOW_KEYWORDS):
            workflow += 0.6
        if has_pending_confirmation and any(
            w in content_lower for w in ("proceed", "confirm", "submit", "approve")
        ):
            workflow += 0.4

        # Importance / unresolved cues
        unresolved = 0.0
        if "?" in msg.content and msg.role == "assistant":
            unresolved += 0.5
        if any(kw in content_lower for kw in _IMPORTANCE_KEYWORDS):
            unresolved += 0.3
        if msg.role == "user" and total - index <= 3:
            unresolved += 0.2

        total_score = (
            self._w_recency * recency
            + self._w_semantic * semantic
            + self._w_workflow * workflow
            + self._w_unresolved * unresolved
        )
        return ScoredMessage(
            message=msg,
            score=total_score,
            factors={
                "recency": recency,
                "semantic": semantic,
                "workflow": workflow,
                "unresolved": unresolved,
            },
        )

    def rank_messages(
        self,
        messages: List[ConversationMessageOut],
        *,
        user_query: Optional[str] = None,
        has_pending_confirmation: bool = False,
        limit: int = 20,
    ) -> List[ConversationMessageOut]:
        if not messages:
            return []
        total = len(messages)
        scored = [
            self.score_message(
                m,
                index=i,
                total=total,
                user_query=user_query,
                has_pending_confirmation=has_pending_confirmation,
            )
            for i, m in enumerate(messages)
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        top = scored[:limit]
        # Re-sort selected by original chronology for LLM coherence
        chronological = sorted(
            top,
            key=lambda s: s.message.created_at or datetime.min.replace(tzinfo=timezone.utc),
        )
        return [s.message for s in chronological]
