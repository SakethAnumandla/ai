"""JSON-safe payloads for OCRBill.extracted_fields (PostgreSQL JSON column)."""
from __future__ import annotations

from typing import Any, Dict, Mapping

from app.ai.json_util import json_safe
from app.intelligence.schemas import FieldConfidence


def field_confidence_to_json(field_confidence: Mapping[str, FieldConfidence]) -> dict:
    """Serialize OCR field confidence map for SQLAlchemy JSON storage."""
    payload = {
        k: v.model_dump(mode="json") for k, v in field_confidence.items()
    }
    return json_safe(payload)


def merge_extracted_fields(existing: Any, updates: Dict[str, Any]) -> dict:
    """Merge keys into extracted_fields and ensure JSON-serializable values."""
    base = dict(existing or {})
    base.update(updates)
    return json_safe(base)
