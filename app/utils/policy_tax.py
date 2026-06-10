"""Bridge policy tax settings → expense tax lines on claims."""
from typing import Any, Dict, List, Optional

from app.models import Expense, Policy
from app.services.tax_service import TaxService
from app.utils.tax_regimes import get_regime


def policy_tax_context(policy: Policy) -> Dict[str, Any]:
    regime = get_regime(policy.country_code or "IN")
    return {
        "country_code": policy.country_code or "IN",
        "tax_regime": policy.tax_regime or (regime["regime_code"] if regime else "india_gst"),
        "applicable_tax_types": policy.applicable_tax_types
        or (regime.get("default_tax_types") if regime else []),
        "tax_inclusive": bool(policy.tax_inclusive),
        "regime_label": regime["regime_label"] if regime else None,
        "currency_symbol": regime["currency_symbol"] if regime else None,
    }


def merge_claim_tax_payload(
    policy: Policy,
    *,
    ocr_data: Optional[Dict[str, Any]] = None,
    tax_lines: Optional[List[Dict[str, Any]]] = None,
    subtotal: Optional[float] = None,
) -> Dict[str, Any]:
    """Build unified tax payload stored on claim OCR data and used for expenses."""
    ctx = policy_tax_context(policy)
    payload: Dict[str, Any] = {
        "country_code": ctx["country_code"],
        "tax_regime": ctx["tax_regime"],
        "subtotal": subtotal,
        "tax_lines": tax_lines or [],
    }
    if ocr_data:
        payload["ocr_tax_breakdown"] = ocr_data.get("tax_breakdown")
        payload["ocr_tax_amount"] = ocr_data.get("tax_amount")
        if subtotal is None and ocr_data.get("subtotal"):
            payload["subtotal"] = ocr_data.get("subtotal")
    return payload


def apply_policy_taxes_to_expense(
    db,
    expense: Expense,
    policy: Policy,
    *,
    ocr_data: Optional[Dict[str, Any]] = None,
    tax_lines: Optional[List[Dict[str, Any]]] = None,
    subtotal: Optional[float] = None,
) -> None:
    """Apply tax lines to expense using policy country/regime."""
    expense.country_code = policy.country_code or "IN"
    if subtotal is not None:
        expense.subtotal = subtotal
    elif ocr_data and ocr_data.get("subtotal"):
        expense.subtotal = float(ocr_data["subtotal"])

    svc = TaxService(db)
    lines = tax_lines or []
    if not lines and ocr_data:
        breakdown = ocr_data.get("tax_breakdown")
        if isinstance(ocr_data.get("tax_payload"), dict):
            tp = ocr_data["tax_payload"]
            lines = tp.get("tax_lines") or lines
            if tp.get("subtotal") and expense.subtotal is None:
                expense.subtotal = tp["subtotal"]
        if not lines:
            svc.import_from_ocr_breakdown(
                expense,
                breakdown,
                total_tax=ocr_data.get("tax_amount"),
                country_code=policy.country_code,
            )
            return
    if lines:
        svc.replace_expense_taxes(expense, lines, country_code=policy.country_code)
    elif ocr_data and ocr_data.get("tax_amount"):
        svc.import_from_ocr_breakdown(
            expense,
            ocr_data.get("tax_breakdown"),
            total_tax=ocr_data.get("tax_amount"),
            country_code=policy.country_code,
        )
