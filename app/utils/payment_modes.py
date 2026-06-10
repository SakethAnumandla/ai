"""Payment mode catalog for manual bills, policies, and claims."""
from typing import Any, Dict, List, Optional

from app.models import PaymentMethod

PAYMENT_MODES: List[Dict[str, Any]] = [
    {"value": PaymentMethod.CASH.value, "label": "Cash", "icon": "💵"},
    {"value": PaymentMethod.UPI.value, "label": "UPI", "icon": "📱"},
    {"value": PaymentMethod.CREDIT_CARD.value, "label": "Credit Card", "icon": "💳"},
    {"value": PaymentMethod.DEBIT_CARD.value, "label": "Debit Card", "icon": "💳"},
    {"value": PaymentMethod.NET_BANKING.value, "label": "Net Banking", "icon": "🏦"},
    {"value": PaymentMethod.WALLET.value, "label": "Wallet", "icon": "👛"},
    {"value": PaymentMethod.CRYPTO.value, "label": "Crypto", "icon": "₿"},
]

PAYMENT_MODE_VALUES = {m["value"] for m in PAYMENT_MODES}

# Aliases from UI / OCR text → canonical value
PAYMENT_ALIASES: Dict[str, str] = {
    "cash": PaymentMethod.CASH.value,
    "upi": PaymentMethod.UPI.value,
    "gpay": PaymentMethod.UPI.value,
    "google pay": PaymentMethod.UPI.value,
    "phonepe": PaymentMethod.UPI.value,
    "paytm": PaymentMethod.WALLET.value,
    "card": PaymentMethod.CREDIT_CARD.value,
    "credit": PaymentMethod.CREDIT_CARD.value,
    "credit card": PaymentMethod.CREDIT_CARD.value,
    "debit": PaymentMethod.DEBIT_CARD.value,
    "debit card": PaymentMethod.DEBIT_CARD.value,
    "net banking": PaymentMethod.NET_BANKING.value,
    "bank transfer": PaymentMethod.NET_BANKING.value,
    "neft": PaymentMethod.NET_BANKING.value,
    "imps": PaymentMethod.NET_BANKING.value,
    "wallet": PaymentMethod.WALLET.value,
    "crypto": PaymentMethod.CRYPTO.value,
}


def list_payment_modes() -> Dict[str, Any]:
    return {
        "payment_modes": PAYMENT_MODES,
        "default": PaymentMethod.UPI.value,
    }


def normalize_payment_mode(value: Optional[str]) -> Optional[str]:
    if not value or not str(value).strip():
        return None
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if key in PAYMENT_MODE_VALUES:
        return key
    if key in PAYMENT_ALIASES:
        return PAYMENT_ALIASES[key]
    key_spaced = str(value).strip().lower()
    if key_spaced in PAYMENT_ALIASES:
        return PAYMENT_ALIASES[key_spaced]
    return None


def payment_mode_label(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    for m in PAYMENT_MODES:
        if m["value"] == value:
            return m["label"]
    return value.replace("_", " ").title()
