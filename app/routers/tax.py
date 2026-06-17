"""Simplified tax configuration for expense entry (no country selection)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps.scope import ExpenseScope, get_expense_scope

from app.utils.tax_regimes import (
    TAX_REGIMES,
    get_regime,
    get_tax_types_catalog,
    list_countries,
)

router = APIRouter(prefix="/tax", tags=["tax"])


@router.get("/config")
async def tax_entry_config(_scope: ExpenseScope = Depends(get_expense_scope)):
    """
    Tax UI configuration for manual expense entry.
    Users add multiple taxes with custom labels and either % or fixed value.
    """
    return {
        "country_selection_required": False,
        "allow_multiple_taxes": True,
        "calculation_types": [
            {"value": "percentage", "label": "Percentage (%)", "requires": ["tax_rate", "tax_amount"]},
            {"value": "fixed_value", "label": "Fixed amount", "requires": ["tax_amount"]},
        ],
        "example_tax_line": {
            "tax_label": "GST",
            "calculation_type": "percentage",
            "tax_rate": 18,
            "taxable_amount": 1000,
            "tax_amount": 180,
        },
        "note": "No country or tax regime selection. Label each tax yourself (e.g. CGST, SGST, VAT).",
    }


@router.get("/types")
async def list_tax_types(_scope: ExpenseScope = Depends(get_expense_scope)):
    """Common tax label suggestions (optional; users can enter any label)."""
    return {
        "suggested_labels": [
            "GST", "CGST", "SGST", "IGST", "VAT", "Service Tax", "TCS", "Other",
        ],
        "tax_types": get_tax_types_catalog(),
        "deprecated": "Use GET /tax/config for entry UI; GET /tax/regimes for country regimes.",
    }


@router.get("/regimes")
async def list_tax_regimes(
    country: Optional[str] = Query(None, description="ISO country code, e.g. IN"),
    _scope: ExpenseScope = Depends(get_expense_scope),
):
    """
    Country tax regimes for manual expense entry and policy defaults.
    Without `country`, returns all supported countries plus full regime catalog.
    """
    if country:
        regime = get_regime(country)
        if not regime:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown country code: {country.upper()}",
            )
        return regime
    return {
        "countries": list_countries(),
        "regimes": list(TAX_REGIMES.values()),
    }
