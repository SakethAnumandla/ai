from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.ai.schemas.audit import TokenUsage


@dataclass
class ToolCallPlan:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ChatWithToolsResult:
    content: str
    tool_calls: List[ToolCallPlan] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: int = 0
    model: str = ""
