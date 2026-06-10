"""Parse tax_lines JSON from multipart form fields."""
from __future__ import annotations

import json
from typing import List, Optional


def parse_tax_lines_form(raw: Optional[str]) -> List[dict]:
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "tax_lines" in data:
            return data["tax_lines"]
    except json.JSONDecodeError:
        pass
    raise ValueError("tax_lines must be a JSON array")
