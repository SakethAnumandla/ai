"""Expense tax lines: CRUD, summaries, OCR import."""
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models import Expense, ExpenseTax
from app.utils.tax_regimes import (
    DEFAULT_COUNTRY_CODE,
    get_regime,
    map_breakdown_key_to_tax_type,
    normalize_tax_type,
)


def _amount_or_zero(v: Optional[float]) -> float:
    return round(float(v or 0), 2)


def coerce_tax_line_dicts(lines: Sequence[Any]) -> List[Dict[str, Any]]:
    """Accept Pydantic models or plain dicts (e.g. from ExpenseUpdate.dict())."""
    out: List[Dict[str, Any]] = []
    for line in lines:
        if hasattr(line, "model_dump"):
            out.append(line.model_dump())
        elif isinstance(line, dict):
            out.append(line)
        else:
            out.append(dict(line))
    return out


def _label_from_line(raw: Dict[str, Any], tax_type: str) -> str:
    label = raw.get("tax_label") or raw.get("tax_type") or tax_type
    return str(label).strip().upper() if str(label).strip() else tax_type.upper()


def _calculation_type(raw: Dict[str, Any]) -> str:
    ct = raw.get("calculation_type") or "fixed_value"
    if ct in ("percentage", "percent", "%"):
        return "percentage"
    return "fixed_value"


def _sync_component_columns(tax_type: str, tax_amount: float, line: Dict[str, Any]) -> Dict[str, float]:
    """Map tax_amount into cgst/sgst/igst/vat columns when not explicitly set."""
    cgst = _amount_or_zero(line.get("cgst"))
    sgst = _amount_or_zero(line.get("sgst"))
    igst = _amount_or_zero(line.get("igst"))
    vat = _amount_or_zero(line.get("vat"))
    amt = _amount_or_zero(tax_amount)

    tt = normalize_tax_type(tax_type)
    if tt == "cgst" and cgst == 0:
        cgst = amt
    elif tt == "sgst" and sgst == 0:
        sgst = amt
    elif tt == "igst" and igst == 0:
        igst = amt
    elif tt in ("vat",) and vat == 0:
        vat = amt

    return {"cgst": cgst, "sgst": sgst, "igst": igst, "vat": vat}


def tax_line_to_dict(row: ExpenseTax) -> Dict[str, Any]:
    label = row.tax_label or row.tax_type
    return {
        "id": row.id,
        "expense_id": row.expense_id,
        "tax_label": label,
        "calculation_type": row.calculation_type or "fixed_value",
        "tax_type": row.tax_type,
        "tax_rate": row.tax_rate,
        "taxable_amount": row.taxable_amount,
        "cgst": row.cgst,
        "sgst": row.sgst,
        "igst": row.igst,
        "vat": row.vat,
        "tax_amount": row.tax_amount,
        "recoverable": row.recoverable,
        "created_at": row.created_at,
        "country_code": row.country_code,
        "tax_regime": row.tax_regime,
    }


def tax_lines_to_create_schema(lines: List[ExpenseTax]) -> List[Dict[str, Any]]:
    """Convert DB tax rows to API create-schema shape for prefill."""
    out: List[Dict[str, Any]] = []
    for row in lines:
        out.append(
            {
                "tax_label": row.tax_label or row.tax_type.upper(),
                "calculation_type": row.calculation_type or "fixed_value",
                "tax_rate": row.tax_rate,
                "tax_amount": row.tax_amount,
                "taxable_amount": row.taxable_amount,
                "recoverable": row.recoverable,
            }
        )
    return out


def build_tax_summary(lines: List[ExpenseTax], country_code: Optional[str] = None) -> Dict[str, Any]:
    cc = country_code or DEFAULT_COUNTRY_CODE
    regime = get_regime(cc) or get_regime(DEFAULT_COUNTRY_CODE)
    total_cgst = sum(_amount_or_zero(l.cgst) for l in lines)
    total_sgst = sum(_amount_or_zero(l.sgst) for l in lines)
    total_igst = sum(_amount_or_zero(l.igst) for l in lines)
    total_vat = sum(_amount_or_zero(l.vat) for l in lines)
    total_tax = sum(_amount_or_zero(l.tax_amount) for l in lines)
    taxable = sum(_amount_or_zero(l.taxable_amount) for l in lines if l.taxable_amount)

    return {
        "country_code": cc,
        "regime_code": regime["regime_code"] if regime else None,
        "regime_label": regime["regime_label"] if regime else None,
        "currency": regime["currency"] if regime else None,
        "currency_symbol": regime["currency_symbol"] if regime else None,
        "line_count": len(lines),
        "taxable_amount": round(taxable, 2) if taxable else None,
        "total_tax": round(total_tax, 2),
        "total_cgst": round(total_cgst, 2),
        "total_sgst": round(total_sgst, 2),
        "total_igst": round(total_igst, 2),
        "total_vat": round(total_vat, 2),
        "total_recoverable": round(
            sum(_amount_or_zero(l.tax_amount) for l in lines if l.recoverable), 2
        ),
        "lines": [tax_line_to_dict(l) for l in lines],
    }


class TaxService:
    def __init__(self, db: Session):
        self.db = db

    def list_for_expense(self, expense_id: int) -> List[ExpenseTax]:
        return (
            self.db.query(ExpenseTax)
            .filter(ExpenseTax.expense_id == expense_id)
            .order_by(ExpenseTax.id.asc())
            .all()
        )

    def replace_expense_taxes(
        self,
        expense: Expense,
        tax_lines: List[Dict[str, Any]],
        *,
        country_code: Optional[str] = None,
    ) -> List[ExpenseTax]:
        """Replace all tax rows for an expense and sync expense.tax_amount."""
        cc = (country_code or expense.country_code or DEFAULT_COUNTRY_CODE).upper()
        regime = get_regime(cc)
        regime_code = regime["regime_code"] if regime else "generic"

        self.db.query(ExpenseTax).filter(ExpenseTax.expense_id == expense.id).delete()

        created: List[ExpenseTax] = []
        for raw in tax_lines:
            tt = normalize_tax_type(raw.get("tax_type") or raw.get("tax_label") or "other")
            tax_label = _label_from_line(raw, tt)
            calc_type = _calculation_type(raw)
            tax_rate = raw.get("tax_rate")
            taxable_amount = raw.get("taxable_amount")
            tax_amount = _amount_or_zero(raw.get("tax_amount"))

            if calc_type == "percentage" and tax_rate is not None and taxable_amount:
                computed = round(float(taxable_amount) * float(tax_rate) / 100, 2)
                if tax_amount <= 0:
                    tax_amount = computed

            if tax_amount <= 0:
                cols = _sync_component_columns(tt, tax_amount, raw)
                tax_amount = cols["cgst"] + cols["sgst"] + cols["igst"] + cols["vat"]
            if tax_amount <= 0:
                continue

            cols = _sync_component_columns(tt, tax_amount, raw)
            row = ExpenseTax(
                expense_id=expense.id,
                country_code=cc,
                tax_regime=raw.get("tax_regime") or regime_code,
                tax_type=tt,
                tax_label=tax_label,
                calculation_type=calc_type,
                tax_rate=tax_rate,
                taxable_amount=taxable_amount,
                cgst=cols["cgst"],
                sgst=cols["sgst"],
                igst=cols["igst"],
                vat=cols["vat"],
                tax_amount=tax_amount,
                recoverable=bool(raw.get("recoverable", True)),
            )
            self.db.add(row)
            created.append(row)

        self.db.flush()
        expense.tax_amount = round(sum(_amount_or_zero(r.tax_amount) for r in created), 2)
        expense.updated_at = datetime.utcnow()
        return created

    def import_from_ocr_breakdown(
        self,
        expense: Expense,
        tax_breakdown: Optional[Dict[str, Any]],
        *,
        total_tax: Optional[float] = None,
        country_code: Optional[str] = None,
    ) -> List[ExpenseTax]:
        """Create tax lines from OCR tax_breakdown dict (each key becomes a labeled tax line)."""
        if not tax_breakdown and not total_tax:
            return []

        lines: List[Dict[str, Any]] = []
        if tax_breakdown:
            for key, value in tax_breakdown.items():
                try:
                    amt = float(value)
                except (TypeError, ValueError):
                    continue
                if amt <= 0:
                    continue
                tt = map_breakdown_key_to_tax_type(key)
                label = str(key).replace("_", " ").upper()
                line: Dict[str, Any] = {
                    "tax_label": label,
                    "tax_type": tt,
                    "calculation_type": "fixed_value",
                    "tax_amount": amt,
                    "recoverable": True,
                }
                if tt == "cgst":
                    line["cgst"] = amt
                elif tt == "sgst":
                    line["sgst"] = amt
                elif tt == "igst":
                    line["igst"] = amt
                elif tt in ("vat",):
                    line["vat"] = amt
                lines.append(line)

        if not lines and total_tax and total_tax > 0:
            lines.append(
                {
                    "tax_label": "TAX",
                    "tax_type": "gst",
                    "calculation_type": "fixed_value",
                    "tax_amount": float(total_tax),
                    "recoverable": True,
                }
            )

        if not lines:
            return []

        return self.replace_expense_taxes(expense, lines, country_code=country_code)
