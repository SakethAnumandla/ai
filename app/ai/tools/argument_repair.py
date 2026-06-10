"""
Deterministic tool argument repair — no GPT re-calls.

Pipeline: normalize → lexical repair → type coercion → validate → execute
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.ai.tools.argument_normalizer import normalize_tool_arguments

logger = logging.getLogger(__name__)

# Spoken / written numbers → float (subset; extend as needed)
_WORD_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_WORD_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_WORD_SCALES = {
    "hundred": 100, "thousand": 1_000, "lakh": 100_000, "lac": 100_000,
    "million": 1_000_000, "crore": 10_000_000, "cr": 10_000_000,
}

_DECISION_ALIASES = {
    "approve": "approved", "approved": "approved", "accept": "approved", "yes": "approved",
    "reject": "rejected", "rejected": "rejected", "deny": "rejected", "no": "rejected",
}

_STATUS_ALIASES = {
    "draft": "draft", "pending": "pending", "approved": "approved", "rejected": "rejected",
}


def _words_to_number(text: str) -> Optional[float]:
    """Parse phrases like 'two thousand', '2k', '₹500'."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().lower()
    s = re.sub(r"[₹$,]", "", s)
    s = re.sub(r"\brs\.?\b", "", s).strip()
    if not s:
        return None

    # Pure numeric
    try:
        return float(s.replace(",", ""))
    except ValueError:
        pass

    # Compact: 2k, 1.5l
    m = re.match(r"^([\d.]+)\s*([kKlL]|cr)$", s)
    if m:
        base = float(m.group(1))
        suf = m.group(2).lower()
        mult = {"k": 1_000, "l": 100_000, "cr": 10_000_000}.get(suf, 1)
        return base * mult

    tokens = re.findall(r"[\w.]+", s)
    if not tokens:
        return None

    total = 0.0
    current = 0.0
    for tok in tokens:
        if tok in _WORD_ONES:
            current += _WORD_ONES[tok]
        elif tok in _WORD_TENS:
            current += _WORD_TENS[tok]
        elif tok in _WORD_SCALES:
            scale = _WORD_SCALES[tok]
            if current == 0:
                current = 1
            current *= scale
            if scale >= 1000:
                total += current
                current = 0.0
        elif tok.replace(".", "", 1).isdigit():
            current += float(tok)
    total += current
    return total if total > 0 else None


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return int(s)
        num = _words_to_number(s)
        if num is not None:
            return int(num)
    return None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        num = _words_to_number(value)
        if num is not None:
            return num
    return None


def _repair_enum(value: Any, allowed: List[str], aliases: Dict[str, str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in allowed:
        return v
    if v in aliases:
        mapped = aliases[v]
        if mapped in allowed:
            return mapped
    return None


class ArgumentRepairResult:
    def __init__(
        self,
        arguments: Dict[str, Any],
        *,
        valid: bool,
        repairs: List[str],
        errors: List[str],
    ):
        self.arguments = arguments
        self.valid = valid
        self.repairs = repairs
        self.errors = errors


def repair_tool_arguments(
    tool_name: str,
    arguments: Dict[str, Any],
    parameters_schema: Dict[str, Any],
) -> ArgumentRepairResult:
    """
    Repair and validate tool arguments against JSON Schema (subset).
    Does not call GPT.
    """
    repairs: List[str] = []
    errors: List[str] = []
    out = normalize_tool_arguments(dict(arguments or {}))

    props = parameters_schema.get("properties") or {}
    required = set(parameters_schema.get("required") or [])

    for key, spec in props.items():
        if key not in out:
            continue
        val = out[key]
        ptype = spec.get("type")

        if ptype == "integer" or key.endswith("_id") or key == "expense_id" or key == "claim_id":
            coerced = _coerce_int(val)
            if coerced is not None and coerced != val:
                repairs.append(f"{key}: {val!r} → {coerced}")
                out[key] = coerced
            elif coerced is None and val is not None:
                errors.append(f"{key}: cannot parse integer from {val!r}")
            elif coerced is not None:
                out[key] = coerced

        elif ptype == "number":
            coerced = _coerce_float(val)
            if coerced is not None:
                if coerced != val:
                    repairs.append(f"{key}: {val!r} → {coerced}")
                out[key] = coerced
            elif val is not None:
                errors.append(f"{key}: cannot parse number from {val!r}")

        elif ptype == "string":
            if key == "decision" and "enum" in spec:
                fixed = _repair_enum(val, spec["enum"], _DECISION_ALIASES)
                if fixed:
                    if fixed != val:
                        repairs.append(f"decision: {val!r} → {fixed}")
                    out[key] = fixed
                elif val is not None:
                    errors.append(f"decision: invalid value {val!r}")
            elif key == "status" and "enum" in spec:
                fixed = _repair_enum(val, spec["enum"], _STATUS_ALIASES)
                if fixed:
                    if fixed != val:
                        repairs.append(f"status: {val!r} → {fixed}")
                    out[key] = fixed
            elif val is not None:
                out[key] = str(val).strip()

    # Amount fields even if schema typing is loose
    for amount_key in ("bill_amount", "amount", "approved_amount"):
        if amount_key in out:
            coerced = _coerce_float(out[amount_key])
            if coerced is not None:
                if coerced != out[amount_key]:
                    repairs.append(f"{amount_key}: {out[amount_key]!r} → {coerced}")
                out[amount_key] = coerced

    for req in required:
        if req not in out or out[req] is None or out[req] == "":
            errors.append(f"Missing required field: {req}")

    if parameters_schema.get("additionalProperties") is False:
        allowed = set(props.keys())
        for k in list(out.keys()):
            if k not in allowed:
                repairs.append(f"dropped unknown field: {k}")
                del out[k]

    valid = len(errors) == 0
    if repairs:
        logger.info("argument_repair", extra={"tool": tool_name, "repairs": repairs})
    return ArgumentRepairResult(out, valid=valid, repairs=repairs, errors=errors)
