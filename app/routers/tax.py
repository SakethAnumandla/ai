"""Simplified tax configuration for expense entry (no country selection)."""
from fastapi import APIRouter

router = APIRouter(prefix="/tax", tags=["tax"])


@router.get("/config")
async def tax_entry_config():
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
async def list_tax_types():
    """Common tax label suggestions (optional; users can enter any label)."""
    return {
        "suggested_labels": [
            "GST", "CGST", "SGST", "IGST", "VAT", "Service Tax", "TCS", "Other",
        ],
        "deprecated": "Country-based regimes removed. Use GET /tax/config instead.",
    }
