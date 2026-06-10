"""Extract expense entities from natural-language messages before slot-filling."""
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.ai.vendor_guard import sanitize_vendor_name

logger = logging.getLogger(__name__)


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# Canonical display names keyed by normalized token
_KNOWN_MERCHANTS: Dict[str, str] = {
    "pizzahut": "Pizza Hut",
    "pizzahutindia": "Pizza Hut",
    "dominos": "Domino's",
    "dominospizza": "Domino's",
    "uber": "Uber",
    "ola": "Ola",
    "amazon": "Amazon",
    "swiggy": "Swiggy",
    "zomato": "Zomato",
    "bawarchi": "Bawarchi",
    "kfc": "KFC",
    "mcdonalds": "McDonald's",
    "mcd": "McDonald's",
    "starbucks": "Starbucks",
    "blinkit": "Blinkit",
    "zepto": "Zepto",
    "bigbasket": "BigBasket",
    "irctc": "IRCTC",
    "makemytrip": "MakeMyTrip",
    "bookmyshow": "BookMyShow",
    "cafecoffeeday": "Cafe Coffee Day",
    "ccd": "Cafe Coffee Day",
}

_CATEGORY_KEYWORDS: Dict[str, str] = {
    "pizza": "food",
    "biryani": "food",
    "burger": "food",
    "pasta": "food",
    "dosa": "food",
    "idli": "food",
    "lunch": "food",
    "dinner": "food",
    "breakfast": "food",
    "brunch": "food",
    "restaurant": "food",
    "cafe": "food",
    "coffee": "food",
    "tea": "food",
    "meal": "food",
    "swiggy": "food",
    "zomato": "food",
    "dominos": "food",
    "pizzahut": "food",
    "uber": "travel",
    "ola": "travel",
    "rapido": "travel",
    "cab": "travel",
    "taxi": "travel",
    "metro": "travel",
    "flight": "travel",
    "hotel": "travel",
    "fuel": "fuel",
    "petrol": "fuel",
    "diesel": "fuel",
    "aws": "subscriptions",
    "netflix": "subscriptions",
    "spotify": "subscriptions",
    "amazon": "shopping",
    "flipkart": "shopping",
    "grocery": "groceries",
    "groceries": "groceries",
}

_PAYMENT_ALIASES: Dict[str, str] = {
    "upi": "upi",
    "gpay": "upi",
    "googlepay": "upi",
    "google pay": "upi",
    "phonepe": "upi",
    "paytm": "upi",
    "bhim": "upi",
    "cash": "cash",
    "credit card": "credit_card",
    "creditcard": "credit_card",
    "credit": "credit_card",
    "debit card": "debit_card",
    "debitcard": "debit_card",
    "debit": "debit_card",
    "wallet": "wallet",
    "net banking": "net_banking",
    "netbanking": "net_banking",
    "visa": "credit_card",
    "mastercard": "credit_card",
    "amex": "credit_card",
}

_AMOUNT_PATTERNS = [
    re.compile(r"\bbill\s+was\s+(?:₹|rs\.?)?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"\b(?:amount|cost|price|total)\s+(?:is|was|=|:)\s*(?:₹|rs\.?)?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"(?:for|₹|rs\.?)\s*(\d+(?:\.\d+)?)\s*(?:rupees?|rs)?", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:rupees?|rs\.?|₹)", re.I),
    re.compile(r"\bspent\s+(?:₹|rs\.?)?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"\b(?:₹|rs\.?)\s*(\d+(?:\.\d+)?)\b", re.I),
]

_GENERIC_VENUE_WORDS = frozenset(
    {
        "hotel",
        "restaurant",
        "cafe",
        "store",
        "shop",
        "place",
        "mall",
        "office",
        "a",
        "the",
        "an",
    }
)

_VENDOR_PATTERNS = [
    re.compile(
        r"\b(?:hotel|restaurant|cafe|store|shop|bar|pub)\s+name\s+is\s+"
        r"([A-Za-z][A-Za-z0-9&'.-]+)",
        re.I,
    ),
    re.compile(
        r"\bname\s+is\s+([A-Za-z][A-Za-z0-9&'.-]+)"
        r"(?=\s+and\b|\s+i\s+had\b|\s+the\s+bill\b|\s+for\b|\s+paid\b|\s+payed\b|\s+using\b)",
        re.I,
    ),
    re.compile(
        r"\b(?:went\s+to|go\s+to|going\s+to|went\s+for)\s+(?:a\s+|the\s+)?"
        r"([A-Za-z][A-Za-z0-9\s&'.-]{2,48}?)"
        r"(?:\s*,|\s+and\s+the\b|\s+had\b|\s+the\s+bill\b|\s+i\s+|\s+for\b|\s+paid\b|\s+payed\b|\s+using\b|$)",
        re.I,
    ),
    re.compile(
        r"\b(?:in|at|from|(?<!went\s)(?<!save\s)(?<!add\s)to|@)\s+([A-Za-z][A-Za-z0-9\s&'.-]{2,48}?)"
        r"(?:\s*,|\s+and\s+the\b|\s+(?:the\s+)?(?:coffee\s+)?bill\b|\s+had\b|\s+i\s+|\s+for\b|\s+paid\b|\s+payed\b|\s+using\b|$)",
        re.I,
    ),
    re.compile(
        r"\bwhich is\s+([A-Za-z][A-Za-z0-9&'.-]{1,48}?)(?:\s+and\b|\s*,|\s+i\s+|\s+for\b|$)",
        re.I,
    ),
    re.compile(
        r"\b(?:merchant|vendor|restaurant|store)\s+(?:is|as|was|=|:)\s+"
        r"([a-z][a-z0-9\s&'.-]{1,48})",
        re.I,
    ),
]

_PAYMENT_PATTERNS = [
    re.compile(
        r"\b(?:paid|payed|pay|payment|using|via|through)\s+(?:with|by|using|via|through)?\s*"
        r"([a-z][a-z0-9\s_-]{1,24})",
        re.I,
    ),
    re.compile(r"\b(?:paid|payed|pay)\s+(?:by|with)\s+([a-z][a-z0-9\s_-]{1,24})", re.I),
    re.compile(
        r"\b(?:paid|payed)\s+(?:it\s+)?(?:using|via|through|with)\s+([a-z][a-z0-9\s_-]{1,24})",
        re.I,
    ),
]

_ITEM_PATTERN = re.compile(
    r"\b(?:had|ate|ordered|bought)\s+([a-z][a-z0-9\s'-]{2,40}?)"
    r"(?:\s*[,;]|\s+(?:in|at|from|for|and)\b)",
    re.I,
)

_STOP_VENDOR_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "my",
        "veg",
        "non",
        "some",
        "something",
        "yesterday",
        "today",
    }
)

# Captures from loose "to/at X" patterns that are not merchants
_INVALID_VENDOR_CAPTURES = frozenset(
    {
        "expense",
        "expenses",
        "bill",
        "receipt",
        "draft",
        "details",
        "approval",
        "wallet",
        "hotel",
        "restaurant",
        "cafe",
        "store",
        "shop",
    }
)


def _title_phrase(value: str) -> str:
    parts = value.strip().split()
    return " ".join(p[:1].upper() + p[1:].lower() if p else "" for p in parts[:5])


@dataclass
class ExtractedExpenseEntities:
    bill_amount: Optional[float] = None
    vendor_name: Optional[str] = None
    payment_method: Optional[str] = None
    main_category: Optional[str] = None
    bill_name: Optional[str] = None

    def to_slot_prefill(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.bill_amount is not None:
            out["bill_amount"] = self.bill_amount
        if self.vendor_name:
            out["vendor_name"] = self.vendor_name
        if self.payment_method:
            out["payment_method"] = self.payment_method
        if self.main_category:
            out["main_category"] = self.main_category
        if self.bill_name:
            out["bill_name"] = self.bill_name
        return out


class ExpenseEntityExtractor:
    """Pre-extract expense fields from a single natural-language utterance."""

    def extract(self, text: str) -> ExtractedExpenseEntities:
        if not (text or "").strip():
            return ExtractedExpenseEntities()

        entities = ExtractedExpenseEntities(
            bill_amount=self._extract_amount(text),
            vendor_name=self._extract_merchant(text),
            payment_method=self._extract_payment(text),
            main_category=self._extract_category(text),
            bill_name=self._extract_description(text),
        )
        logger.info(
            "Expense entities extracted: %s",
            entities.to_slot_prefill(),
        )
        return entities

    def _extract_amount(self, text: str) -> Optional[float]:
        for pattern in _AMOUNT_PATTERNS:
            m = pattern.search(text)
            if m:
                try:
                    val = float(m.group(1))
                    if val > 0:
                        return val
                except ValueError:
                    continue
        return None

    def _extract_merchant(self, text: str) -> Optional[str]:
        lowered = text.lower()
        compact = _normalize_key(lowered)

        for key, canonical in _KNOWN_MERCHANTS.items():
            if key in compact:
                return canonical

        for pattern in _VENDOR_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            raw = m.group(1).strip()
            raw = re.split(
                r"\s+and\s+(?=(?:the\s+)?(?:hotel\s+)?name\b|(?:the\s+)?bill\b|i\s+|had\b|paid\b|payed\b|using\b|for\b)",
                raw,
                maxsplit=1,
                flags=re.I,
            )[0].strip()
            if not raw or raw.lower() in _STOP_VENDOR_WORDS:
                continue
            if _normalize_key(raw) in _GENERIC_VENUE_WORDS:
                continue
            if raw.lower() in _INVALID_VENDOR_CAPTURES:
                continue
            known = _KNOWN_MERCHANTS.get(_normalize_key(raw))
            if known:
                return known
            titled = _title_phrase(raw)
            return sanitize_vendor_name(titled)

        return None

    def _extract_payment(self, text: str) -> Optional[str]:
        lowered = text.lower()
        for alias in sorted(_PAYMENT_ALIASES.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                return _PAYMENT_ALIASES[alias]

        for pattern in _PAYMENT_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            fragment = m.group(1).strip().lower()
            fragment = re.split(r"\s+and\b", fragment, maxsplit=1)[0].strip()
            for alias in sorted(_PAYMENT_ALIASES.keys(), key=len, reverse=True):
                if alias in fragment.replace("_", " "):
                    return _PAYMENT_ALIASES[alias]
            compact = fragment.replace(" ", "")
            if compact in _PAYMENT_ALIASES:
                return _PAYMENT_ALIASES[compact]
        return None

    def _extract_category(self, text: str) -> Optional[str]:
        lowered = text.lower()
        vendor = self._extract_merchant(text)
        if vendor:
            vkey = _normalize_key(vendor)
            if vkey in _CATEGORY_KEYWORDS:
                return _CATEGORY_KEYWORDS[vkey]

        for keyword, category in _CATEGORY_KEYWORDS.items():
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                return category
        return None

    def _extract_description(self, text: str) -> Optional[str]:
        m = _ITEM_PATTERN.search(text)
        if m:
            item = m.group(1).strip()
            if item and item.lower() not in _STOP_VENDOR_WORDS:
                return _title_phrase(item)
        return None
