"""Parse tax_lines JSON from multipart form fields."""
from __future__ import annotations

import json
from typing import Any, List, Optional


def parse_tax_lines_form(raw: Optional[str]) -> List[dict]:
    """Accept JSON array or ``{"tax_lines": [...]}`` from multipart forms."""
    if not raw or not str(raw).strip():
        return []
    text = str(raw).strip()
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"tax_lines must be valid JSON (array of tax line objects): {exc.msg}"
        ) from exc
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "tax_lines" in data:
        lines = data["tax_lines"]
        if isinstance(lines, list):
            return lines
        raise ValueError("tax_lines.tax_lines must be a JSON array")
    raise ValueError(
        'tax_lines must be a JSON array or an object like {"tax_lines": [...]}'
    )
