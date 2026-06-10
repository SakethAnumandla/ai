"""Normalize tool arguments for better UX (2k → 2000, tmrw → tomorrow)."""
import re
from datetime import datetime, timedelta
from typing import Any, Dict

_VENDOR_ALIASES = {
    "uber": "Uber",
    "ola": "Ola",
    "rapido": "Rapido",
    "swiggy": "Swiggy",
    "zomato": "Zomato",
    "amazon": "Amazon",
}

_AMOUNT_SUFFIX = {
    "k": 1_000,
    "l": 100_000,
    "lac": 100_000,
    "lakh": 100_000,
    "cr": 10_000_000,
}


def _normalize_amount(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return value
    s = value.strip().lower().replace(",", "").replace("₹", "").replace("rs", "").strip()
    if not s:
        return value
    for suffix, mult in _AMOUNT_SUFFIX.items():
        if s.endswith(suffix):
            try:
                num = float(s[: -len(suffix)].strip())
                return num * mult
            except ValueError:
                pass
    try:
        return float(s)
    except ValueError:
        return value


def _normalize_vendor(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    key = value.strip().lower()
    return _VENDOR_ALIASES.get(key, value.strip().title())


def _normalize_date(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    s = value.strip().lower()
    today = datetime.utcnow().date()
    if s in ("today", "now"):
        return today.isoformat()
    if s in ("tomorrow", "tmrw", "tmr"):
        return (today + timedelta(days=1)).isoformat()
    if s in ("yesterday", "yday"):
        return (today - timedelta(days=1)).isoformat()
    return value


def normalize_tool_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Apply field-aware normalization to tool arguments."""
    from app.services.expense_enrichment_service import apply_field_aliases

    out = apply_field_aliases(dict(arguments))

    amount_keys = ("bill_amount", "amount", "tax_amount", "discount_amount")
    vendor_keys = ("vendor_name", "bill_name")
    date_keys = ("bill_date", "date", "expense_date")

    for key in amount_keys:
        if key in out:
            out[key] = _normalize_amount(out[key])
    for key in vendor_keys:
        if key in out:
            out[key] = _normalize_vendor(out[key])
    for key in date_keys:
        if key in out:
            out[key] = _normalize_date(out[key])

    if "bill_name" in out and isinstance(out["bill_name"], str):
        from app.ai.tools.expense_create_enrichment import bill_name_needs_repair

        name = out["bill_name"].strip()
        if not bill_name_needs_repair(name):
            out["bill_name"] = name.title()

    return out
