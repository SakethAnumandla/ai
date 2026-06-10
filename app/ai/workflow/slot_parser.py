"""Parse slot updates from follow-up messages during an active expense workflow."""
import re
from typing import Any, Dict, Optional


_SUB_CATEGORY_PATTERNS = [
    re.compile(
        r"\b(?:sub\s*[- ]?category|subcategory)\s+(?:as|is|=|:)\s+([a-z][a-z0-9\s'-]{1,40})",
        re.I,
    ),
    re.compile(r"\bmention\s+sub\s*[- ]?category\s+as\s+([a-z][a-z0-9\s'-]{1,40})", re.I),
    re.compile(r"\bset\s+sub\s*[- ]?category\s+(?:to|as)\s+([a-z][a-z0-9\s'-]{1,40})", re.I),
]

_VENDOR_PATTERNS = [
    re.compile(
        r"\b(?:hotel|restaurant|cafe|store|shop)\s+name\s+is\s+([a-z][a-z0-9\s&'.-]{1,48})",
        re.I,
    ),
    re.compile(r"\b(?:merchant|vendor)\s+(?:is|as|=|:)\s+([a-z][a-z0-9\s&'.-]{1,48})", re.I),
]

_AMOUNT_PATTERNS = [
    re.compile(r"\b(?:amount|bill)\s+(?:is|was|=|:)\s*(?:₹|rs\.?)?\s*(\d+(?:\.\d+)?)", re.I),
]

_CATEGORY_PATTERNS = [
    re.compile(
        r"(?<!sub\s)(?<!sub-)\b(?:main\s+category|category)\s+(?:is|as|=|:)\s+([a-z][a-z0-9\s_-]{1,32})",
        re.I,
    ),
]


def _title(value: str) -> str:
    return " ".join(p[:1].upper() + p[1:].lower() if p else "" for p in value.strip().split()[:4])


_FOOD_SUB_ALIASES = {
    "biryani": "restaurant",
    "restaurant": "restaurant",
    "dining": "dining",
    "lunch": "restaurant",
    "dinner": "dining",
    "cafe": "cafe",
    "coffee": "cafe",
    "team_lunch": "office_lunch",
    "office_lunch": "office_lunch",
}

# Dish / meal words — not valid sub-categories; map to restaurant when user mentions them
_FOOD_DISH_WORDS = frozenset(
    {
        "biryani",
        "pizza",
        "burger",
        "pasta",
        "thali",
        "dosa",
        "idli",
        "curry",
        "noodles",
        "sandwich",
        "breakfast",
        "brunch",
    }
)

_FOOD_SUB_CATEGORY_OPTIONS = "restaurant, dining, cafe, office lunch, groceries, swiggy, zomato"

_PAYMENT_METHOD_WORDS = frozenset(
    {
        "upi",
        "cash",
        "credit",
        "debit",
        "wallet",
        "card",
        "netbanking",
        "net_banking",
        "gpay",
        "phonepe",
        "paytm",
        "visa",
        "mastercard",
        "amex",
    }
)

_PAYMENT_PHRASE = re.compile(
    r"\b(?:paid|pay|payment|using|via|through)\b",
    re.I,
)


def is_payment_method_text(text: Optional[str]) -> bool:
    """True when the message is only (or primarily) a payment method answer."""
    if not (text or "").strip():
        return False
    lowered = text.strip().lower()
    tokens = re.findall(r"[a-z][a-z0-9_]*", lowered)
    if not tokens:
        return False
    if any(t in _PAYMENT_METHOD_WORDS for t in tokens):
        return True
    compact = lowered.replace(" ", "_").replace("-", "_")
    return compact in _PAYMENT_METHOD_WORDS


def normalize_sub_category(main_category: Optional[str], sub_category: str) -> str:
    """Map conversational labels to valid FoodSubCategory values."""
    key = sub_category.strip().lower().replace(" ", "_")
    main = (main_category or "").lower()
    if main == "food":
        if key in _FOOD_DISH_WORDS:
            return "restaurant"
        return _FOOD_SUB_ALIASES.get(key, key)
    return key


def infer_food_sub_category(
    *,
    vendor_name: Optional[str] = None,
    bill_name: Optional[str] = None,
) -> Optional[str]:
    """Default food sub-category from lunch/dinner/restaurant context."""
    hints = " ".join(
        filter(None, [(bill_name or "").lower(), (vendor_name or "").lower()])
    )
    if not hints:
        return None
    if "cafe" in hints or "coffee" in hints:
        return "cafe"
    if "office" in hints or "team lunch" in hints:
        return "office_lunch"
    if any(
        w in hints
        for w in (
            "lunch",
            "dinner",
            "restaurant",
            "biryani",
            "meal",
            "food",
            "bawarchi",
        )
    ):
        return "restaurant"
    return None


def sanitize_sub_category(
    main_category: Optional[str],
    sub_category: Optional[str],
    *,
    vendor_name: Optional[str] = None,
    bill_name: Optional[str] = None,
) -> Optional[str]:
    """
    Return a schema-valid sub_category, or infer one for food; None if unknown.
    Never pass dish names (e.g. biryani) through as raw sub_category.
    """
    from app.schemas import CATEGORY_SUBCATEGORY_MAPPING, MainCategory

    main_raw = (main_category or "").strip().lower()
    if not main_raw:
        return None
    try:
        main_enum = MainCategory(main_raw)
    except ValueError:
        return None

    valid = set(CATEGORY_SUBCATEGORY_MAPPING.get(main_enum, []))
    if not valid:
        return None

    if sub_category:
        if is_payment_method_text(sub_category):
            sub_category = None
        else:
            candidate = normalize_sub_category(main_category, sub_category)
            if candidate.lower() in valid:
                return candidate.lower()

    if main_enum == MainCategory.FOOD:
        return infer_food_sub_category(vendor_name=vendor_name, bill_name=bill_name)
    return None


def food_sub_category_prompt() -> str:
    return (
        f"What type of food expense is this? (e.g. {_FOOD_SUB_CATEGORY_OPTIONS})"
    )


def parse_slot_updates(text: str) -> Dict[str, Any]:
    """Extract explicit slot assignments from a user message."""
    updates: Dict[str, Any] = {}
    if not (text or "").strip():
        return updates

    for pattern in _SUB_CATEGORY_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = _title(m.group(1))
            updates["sub_category_raw"] = raw
            main = updates.get("main_category") or "food"
            mapped = sanitize_sub_category(main, raw)
            if mapped:
                updates["sub_category"] = mapped
            else:
                updates["sub_category_raw"] = raw
            break

    for pattern in _VENDOR_PATTERNS:
        m = pattern.search(text)
        if m:
            updates["vendor_name"] = _title(m.group(1))
            break

    for pattern in _AMOUNT_PATTERNS:
        m = pattern.search(text)
        if m:
            updates["bill_amount"] = float(m.group(1))
            break

    for pattern in _CATEGORY_PATTERNS:
        m = pattern.search(text)
        if m:
            updates["main_category"] = m.group(1).strip().lower().replace(" ", "_")
            break

    return updates


def is_workflow_slot_message(text: str) -> bool:
    """True when the message looks like filling a field, not starting a new topic."""
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    if parse_slot_updates(text):
        return True
    markers = (
        "sub category",
        "subcategory",
        "merchant",
        "vendor",
        "amount",
        "category",
        "payment method",
        "paid via",
        "save the draft",
        "save this",
    )
    return any(m in lowered for m in markers)
