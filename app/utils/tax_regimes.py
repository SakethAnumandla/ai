"""Country tax regimes, components, and defaults for manual expense entry."""
from typing import Any, Dict, List, Optional

# tax_type values stored on expense_taxes.tax_type
TAX_TYPES: List[Dict[str, Any]] = [
    {"code": "cgst", "label": "CGST", "column": "cgst", "description": "Central GST (India)"},
    {"code": "sgst", "label": "SGST", "column": "sgst", "description": "State GST (India)"},
    {"code": "igst", "label": "IGST", "column": "igst", "description": "Integrated GST (India inter-state)"},
    {"code": "vat", "label": "VAT", "column": "vat", "description": "Value Added Tax"},
    {"code": "sales_tax", "label": "Sales Tax", "column": "tax_amount", "description": "US / generic sales tax"},
    {"code": "service_tax", "label": "Service Tax", "column": "tax_amount", "description": "Legacy service tax"},
    {"code": "gst", "label": "GST", "column": "tax_amount", "description": "Generic GST"},
    {"code": "excise", "label": "Excise", "column": "tax_amount", "description": "Excise duty"},
    {"code": "other", "label": "Other Tax", "column": "tax_amount", "description": "Other / custom"},
]

TAX_TYPE_CODES = {t["code"] for t in TAX_TYPES}

# Country → regime → applicable tax_type codes + default rates (%)
TAX_REGIMES: Dict[str, Dict[str, Any]] = {
    "IN": {
        "country_code": "IN",
        "country_name": "India",
        "regime_code": "india_gst",
        "regime_label": "India GST",
        "currency": "INR",
        "currency_symbol": "₹",
        "default_tax_types": ["cgst", "sgst", "igst"],
        "supports_split_gst": True,
        "components": [
            {
                "tax_type": "cgst",
                "label": "CGST",
                "default_rates": [2.5, 5, 6, 9, 14],
                "recoverable_default": True,
            },
            {
                "tax_type": "sgst",
                "label": "SGST",
                "default_rates": [2.5, 5, 6, 9, 14],
                "recoverable_default": True,
            },
            {
                "tax_type": "igst",
                "label": "IGST",
                "default_rates": [5, 12, 18, 28],
                "recoverable_default": True,
            },
        ],
        "common_slabs": [
            {"label": "GST 5%", "cgst_rate": 2.5, "sgst_rate": 2.5},
            {"label": "GST 12%", "cgst_rate": 6, "sgst_rate": 6},
            {"label": "GST 18%", "cgst_rate": 9, "sgst_rate": 9},
            {"label": "GST 28%", "cgst_rate": 14, "sgst_rate": 14},
            {"label": "IGST 18%", "igst_rate": 18},
        ],
    },
    "AE": {
        "country_code": "AE",
        "country_name": "United Arab Emirates",
        "regime_code": "uae_vat",
        "regime_label": "UAE VAT",
        "currency": "AED",
        "currency_symbol": "د.إ",
        "default_tax_types": ["vat"],
        "supports_split_gst": False,
        "components": [
            {
                "tax_type": "vat",
                "label": "VAT",
                "default_rates": [5],
                "recoverable_default": True,
            },
        ],
        "common_slabs": [{"label": "VAT 5%", "vat_rate": 5}],
    },
    "GB": {
        "country_code": "GB",
        "country_name": "United Kingdom",
        "regime_code": "uk_vat",
        "regime_label": "UK VAT",
        "currency": "GBP",
        "currency_symbol": "£",
        "default_tax_types": ["vat"],
        "supports_split_gst": False,
        "components": [
            {
                "tax_type": "vat",
                "label": "VAT",
                "default_rates": [0, 5, 20],
                "recoverable_default": True,
            },
        ],
        "common_slabs": [
            {"label": "Standard VAT 20%", "vat_rate": 20},
            {"label": "Reduced VAT 5%", "vat_rate": 5},
        ],
    },
    "US": {
        "country_code": "US",
        "country_name": "United States",
        "regime_code": "us_sales_tax",
        "regime_label": "US Sales Tax",
        "currency": "USD",
        "currency_symbol": "$",
        "default_tax_types": ["sales_tax"],
        "supports_split_gst": False,
        "components": [
            {
                "tax_type": "sales_tax",
                "label": "Sales Tax",
                "default_rates": [0, 4, 6, 7, 8.25, 10],
                "recoverable_default": False,
            },
        ],
        "common_slabs": [],
    },
    "DE": {
        "country_code": "DE",
        "country_name": "Germany",
        "regime_code": "eu_vat",
        "regime_label": "EU VAT",
        "currency": "EUR",
        "currency_symbol": "€",
        "default_tax_types": ["vat"],
        "supports_split_gst": False,
        "components": [
            {
                "tax_type": "vat",
                "label": "VAT (MwSt)",
                "default_rates": [7, 19],
                "recoverable_default": True,
            },
        ],
        "common_slabs": [
            {"label": "Standard 19%", "vat_rate": 19},
            {"label": "Reduced 7%", "vat_rate": 7},
        ],
    },
    "SG": {
        "country_code": "SG",
        "country_name": "Singapore",
        "regime_code": "sg_gst",
        "regime_label": "Singapore GST",
        "currency": "SGD",
        "currency_symbol": "S$",
        "default_tax_types": ["gst"],
        "supports_split_gst": False,
        "components": [
            {
                "tax_type": "gst",
                "label": "GST",
                "default_rates": [9],
                "recoverable_default": True,
            },
        ],
        "common_slabs": [{"label": "GST 9%", "gst_rate": 9}],
    },
}

DEFAULT_COUNTRY_CODE = "IN"

# Default tax regime when creating a policy by type (manual or OCR)
POLICY_TYPE_DEFAULT_TAX: Dict[str, Dict[str, Any]] = {
    "medical": {"country_code": "IN", "tax_regime": "india_gst", "applicable_tax_types": ["cgst", "sgst", "igst"]},
    "healthcare": {"country_code": "IN", "tax_regime": "india_gst", "applicable_tax_types": ["cgst", "sgst", "igst"]},
    "travel": {"country_code": "IN", "tax_regime": "india_gst", "applicable_tax_types": ["cgst", "sgst", "igst"]},
    "food": {"country_code": "IN", "tax_regime": "india_gst", "applicable_tax_types": ["cgst", "sgst"]},
    "education": {"country_code": "IN", "tax_regime": "india_gst", "applicable_tax_types": ["cgst", "sgst"]},
    "fuel": {"country_code": "IN", "tax_regime": "india_gst", "applicable_tax_types": ["cgst", "sgst"]},
    "utilities": {"country_code": "IN", "tax_regime": "india_gst", "applicable_tax_types": ["cgst", "sgst", "igst"]},
    "general": {"country_code": "IN", "tax_regime": "india_gst", "applicable_tax_types": ["cgst", "sgst", "igst"]},
}


def default_tax_for_policy_type(policy_type: str) -> Dict[str, Any]:
    pt = (policy_type or "general").lower()
    return dict(POLICY_TYPE_DEFAULT_TAX.get(pt, POLICY_TYPE_DEFAULT_TAX["general"]))


def detect_country_from_text(text: str) -> Optional[str]:
    lower = (text or "").lower()
    if any(x in lower for x in ("gst", "cgst", "sgst", "igst", "india", "inr", "₹", "rs.")):
        return "IN"
    if any(x in lower for x in ("uae", "aed", "dubai", "vat 5%")):
        return "AE"
    if any(x in lower for x in ("united kingdom", "uk vat", "gbp", "£")):
        return "GB"
    if any(x in lower for x in ("sales tax", "united states", "usd")):
        return "US"
    if any(x in lower for x in ("mwst", "germany", "eur")):
        return "DE"
    return None


def resolve_policy_tax_settings(
    policy_type: str,
    *,
    country_code: Optional[str] = None,
    tax_regime: Optional[str] = None,
    applicable_tax_types: Optional[List[str]] = None,
    document_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge explicit fields, document OCR, and policy-type defaults."""
    base = default_tax_for_policy_type(policy_type)
    cc = (country_code or "").upper()[:2] if country_code else None
    if not cc and document_text:
        cc = detect_country_from_text(document_text)
    if not cc:
        cc = base["country_code"]

    regime = get_regime(cc)
    tr = tax_regime or (regime["regime_code"] if regime else base["tax_regime"])
    types = applicable_tax_types or base.get("applicable_tax_types")
    if regime and not applicable_tax_types:
        types = regime.get("default_tax_types", types)

    return {
        "country_code": cc,
        "tax_regime": tr,
        "applicable_tax_types": types,
        "tax_regime_detail": regime,
    }


def list_countries() -> List[Dict[str, Any]]:
    return [
        {
            "country_code": r["country_code"],
            "country_name": r["country_name"],
            "regime_code": r["regime_code"],
            "regime_label": r["regime_label"],
            "currency": r["currency"],
            "currency_symbol": r["currency_symbol"],
        }
        for r in TAX_REGIMES.values()
    ]


def get_regime(country_code: str) -> Optional[Dict[str, Any]]:
    return TAX_REGIMES.get((country_code or DEFAULT_COUNTRY_CODE).upper())


def get_tax_types_catalog() -> List[Dict[str, Any]]:
    return TAX_TYPES


def normalize_tax_type(code: str) -> str:
    c = (code or "other").lower().strip()
    return c if c in TAX_TYPE_CODES else "other"


def map_breakdown_key_to_tax_type(key: str) -> str:
    k = (key or "").lower().strip()
    if k in TAX_TYPE_CODES:
        return k
    if k in ("cast",):
        return "cgst"
    if k == "tax":
        return "gst"
    return "other"
