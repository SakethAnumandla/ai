"""
Post-processing classifier for assistant responses before production delivery.

Labels: SAFE | NEEDS_CLARIFICATION | BLOCKED | ACTIONABLE
"""
import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ResponseClassification(str, Enum):
    SAFE = "SAFE"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    BLOCKED = "BLOCKED"
    ACTIONABLE = "ACTIONABLE"


_BLOCKED_PATTERNS = (
    r"\b(eval|exec|__import__|os\.system|subprocess)\s*\(",
    r"\b(drop\s+table|delete\s+from\s+\w+|;\s*--)",
    r"\bignore\s+(all\s+)?(previous|prior)\s+instructions\b",
    r"\bjailbreak\b",
)

_CLARIFICATION_PATTERNS = (
    r"\?",
    r"\b(please\s+)?(provide|specify|clarify|confirm|which|what\s+is)\b",
    r"\b(missing|required|need\s+more)\b",
    r"\b(could\s+you|can\s+you)\s+(tell|share|send)\b",
)

_ACTIONABLE_PATTERNS = (
    r"\b(submit|create|approve|reject|reimburse|draft)\b",
    r"\b(expense\.(create|submit)|approval\.submit|reimbursement\.submit)\b",
    r"\b(i('ve|\s+have)\s+(created|submitted|drafted))\b",
    r"\btool_call\b",
)

_BLOCK_KEYWORDS = (
    "cannot help with",
    "not allowed",
    "policy violation",
    "compliance issue",
    "i must refuse",
)


class ClassifiedResponse(BaseModel):
    classification: ResponseClassification
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)
    content: str


class ResponseClassifier:
    """Rule-based classifier; swap for LLM judge in production if needed."""

    def classify(self, content: str, *, suggested_tools: Optional[List[str]] = None) -> ClassifiedResponse:
        text = (content or "").strip()
        lowered = text.lower()
        reasons: List[str] = []

        for pattern in _BLOCKED_PATTERNS:
            if re.search(pattern, lowered, re.IGNORECASE):
                reasons.append(f"blocked_pattern:{pattern[:30]}")
                return ClassifiedResponse(
                    classification=ResponseClassification.BLOCKED,
                    confidence=0.95,
                    reasons=reasons,
                    content=text,
                )

        for kw in _BLOCK_KEYWORDS:
            if kw in lowered:
                reasons.append(f"blocked_keyword:{kw}")
                return ClassifiedResponse(
                    classification=ResponseClassification.BLOCKED,
                    confidence=0.9,
                    reasons=reasons,
                    content=text,
                )

        if suggested_tools:
            reasons.append("tool_calls_present")
            return ClassifiedResponse(
                classification=ResponseClassification.ACTIONABLE,
                confidence=0.92,
                reasons=reasons,
                content=text,
            )

        for pattern in _ACTIONABLE_PATTERNS:
            if re.search(pattern, lowered, re.IGNORECASE):
                reasons.append("actionable_intent")
                return ClassifiedResponse(
                    classification=ResponseClassification.ACTIONABLE,
                    confidence=0.85,
                    reasons=reasons,
                    content=text,
                )

        clarification_score = sum(
            1 for p in _CLARIFICATION_PATTERNS if re.search(p, lowered, re.IGNORECASE)
        )
        if clarification_score >= 2 or (clarification_score >= 1 and "?" in text):
            reasons.append("clarification_cues")
            return ClassifiedResponse(
                classification=ResponseClassification.NEEDS_CLARIFICATION,
                confidence=min(0.5 + clarification_score * 0.15, 0.95),
                reasons=reasons,
                content=text,
            )

        reasons.append("informational")
        return ClassifiedResponse(
            classification=ResponseClassification.SAFE,
            confidence=0.8,
            reasons=reasons,
            content=text,
        )
