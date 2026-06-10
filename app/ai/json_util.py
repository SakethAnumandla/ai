"""JSON-safe serialization for AI memory stored in PostgreSQL JSON columns."""
from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from typing import Any


def json_safe(value: Any) -> Any:
    """Recursively convert values to JSON-serializable forms."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(mode="json"))
    return str(value)


def draft_context_to_storage(draft: Any) -> dict:
    """DraftExpenseContext → dict safe for SQLAlchemy JSON column."""
    if hasattr(draft, "model_dump"):
        payload = draft.model_dump(mode="json")
    else:
        payload = draft
    return json_safe(payload)
