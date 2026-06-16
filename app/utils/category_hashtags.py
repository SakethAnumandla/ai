"""Manual expense categories and AI-style hashtag recommendations."""
from typing import Any, Dict, List, Optional

from app.data.business_taxonomy import LEGACY_MAIN_TO_BUSINESS
from app.models import MainCategory

def _load_manual_main_categories() -> List[Dict[str, str]]:
    from app.data.business_taxonomy import BUSINESS_TAXONOMY

    return [
        {
            "value": key,
            "label": meta["label"],
            "icon": meta.get("icon", ""),
            "color": meta.get("color", "#607D8B"),
        }
        for key, meta in BUSINESS_TAXONOMY.items()
    ]


MANUAL_MAIN_CATEGORIES: List[Dict[str, str]] = _load_manual_main_categories()
MANUAL_CATEGORY_VALUES = {c["value"] for c in MANUAL_MAIN_CATEGORIES}

# Map DB/OCR categories to manual picker value for hashtags & UI
_OCR_TO_MANUAL: Dict[str, str] = {
    MainCategory.TRAVEL.value: "travel",
    MainCategory.FOOD.value: "food",
    MainCategory.UTILITIES.value: "utilities",
    MainCategory.BILLS.value: "utilities",
    MainCategory.FUEL.value: "fuel",
    MainCategory.SHOPPING.value: "shopping",
    MainCategory.SUBSCRIPTIONS.value: "subscriptions",
    MainCategory.ENTERTAINMENT.value: "subscriptions",
    MainCategory.GROCERIES.value: "food",
}

_CATEGORY_HASHTAGS: Dict[str, List[str]] = {
    "travel": [
        "#travel",
        "#commute",
        "#uber",
        "#ola",
        "#rapido",
        "#taxi",
        "#cab",
        "#metro",
        "#bus",
        "#train",
        "#flight",
        "#parking",
        "#toll",
        "#business-travel",
        "#travel-food",
        "#travel-meals",
    ],
    "travel_transportation": [
        "#travel",
        "#business-travel",
        "#flight",
        "#hotel",
        "#cab",
        "#travel-food",
        "#travel-meals",
        "#travel-entertainment",
    ],
    "food": [
        "#food",
        "#vegfood",
        "#nonveg",
        "#dining",
        "#delivery",
        "#swiggy",
        "#zomato",
        "#restaurant",
        "#cafe",
        "#snacks",
        "#breakfast",
        "#lunch",
        "#dinner",
        "#office-lunch",
    ],
    "utilities": [
        "#utilities",
        "#mobile",
        "#wifi",
        "#internet",
        "#broadband",
        "#electricity",
        "#water",
        "#gas",
        "#dth",
        "#airtel",
        "#jio",
        "#bsnl",
        "#postpaid",
        "#prepaid",
    ],
    "fuel": [
        "#fuel",
        "#petrol",
        "#diesel",
        "#cng",
        "#evcharging",
        "#highway",
        "#fleet",
    ],
    "shopping": [
        "#shopping",
        "#amazon",
        "#flipkart",
        "#clothing",
        "#electronics",
        "#groceries",
        "#home",
        "#fashion",
        "#online-order",
    ],
    "subscriptions": [
        "#subscriptions",
        "#netflix",
        "#prime",
        "#hotstar",
        "#spotify",
        "#youtube",
        "#membership",
        "#saas",
        "#annual-plan",
    ],
}

_SUBCATEGORY_EXTRA: Dict[str, Dict[str, List[str]]] = {
    "food": {
        "swiggy": ["#swiggy", "#delivery"],
        "zomato": ["#zomato", "#delivery"],
        "restaurant": ["#restaurant", "#dining"],
        "veg": ["#vegfood"],
    },
    "utilities": {
        "mobile": ["#mobile", "#postpaid"],
        "internet": ["#wifi", "#internet", "#broadband"],
        "electricity": ["#electricity"],
    },
    "travel": {
        "uber": ["#uber"],
        "ola": ["#ola"],
        "rapido": ["#rapido"],
        "food_during_travel": ["#travel-food", "#dining", "#meals"],
        "entertainment_during_travel": ["#travel-entertainment", "#events"],
    },
    "travel_transportation": {
        "domestic_travel": ["#flight", "#train", "#bus"],
        "international_travel": ["#international-travel", "#visa"],
        "accommodation": ["#hotel", "#lodging"],
        "food_during_travel": ["#travel-food", "#dining", "#meals", "#lunch", "#dinner"],
        "entertainment_during_travel": ["#travel-entertainment", "#events", "#sightseeing"],
    },
}


def normalize_hashtag(tag: str) -> str:
    """Return a plain tag for JSON/DB storage (no leading #)."""
    t = str(tag).strip()
    while t.startswith("#"):
        t = t[1:].strip()
    if not t:
        return ""
    return t.replace(" ", "-").lower()


def normalize_hashtags_list(tags: Optional[List[str]]) -> List[str]:
    """Deduplicated hashtags for DB/API storage (never includes #)."""
    if not tags:
        return []
    seen: set = set()
    out: List[str] = []
    for raw in tags:
        n = normalize_hashtag(str(raw))
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def parse_hashtags_input(raw: Optional[str]) -> List[str]:
    """Parse JSON array, comma-separated, or space-separated hashtags from a form field."""
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("["):
        import json

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return normalize_hashtags_list([str(x) for x in data if str(x).strip()])
        except json.JSONDecodeError:
            pass
    parts = raw.replace(",", " ").split()
    return normalize_hashtags_list(parts)


def to_manual_category(main_category: str, sub_category: Optional[str] = None) -> str:
    """Map OCR/DB main_category to manual picker value."""
    key = (main_category or "").lower()
    if key in MANUAL_CATEGORY_VALUES:
        return key
    if sub_category and sub_category.lower() in MANUAL_CATEGORY_VALUES:
        return sub_category.lower()
    if key in LEGACY_MAIN_TO_BUSINESS:
        return LEGACY_MAIN_TO_BUSINESS[key]
    return _OCR_TO_MANUAL.get(key, key if key in MANUAL_CATEGORY_VALUES else "miscellaneous")


def main_category_from_manual(manual_value: str) -> MainCategory:
    """Map manual picker value to Expense.main_category enum."""
    key = manual_value.lower()
    business_map = {
        "people_hr": MainCategory.PEOPLE_HR,
        "office_facilities": MainCategory.OFFICE_FACILITIES,
        "technology_it": MainCategory.TECHNOLOGY_IT,
        "travel_transportation": MainCategory.TRAVEL_TRANSPORTATION,
        "meals_entertainment": MainCategory.MEALS_ENTERTAINMENT,
        "sales_marketing": MainCategory.SALES_MARKETING,
        "professional_legal": MainCategory.PROFESSIONAL_LEGAL,
        "finance_banking": MainCategory.FINANCE_BANKING,
        "operations_supply": MainCategory.OPERATIONS_SUPPLY,
        "taxes_govt": MainCategory.TAXES_GOVT,
        "others": MainCategory.OTHERS,
    }
    if key in business_map:
        return business_map[key]
    mapping = {
        "travel": MainCategory.TRAVEL,
        "food": MainCategory.FOOD,
        "utilities": MainCategory.UTILITIES,
        "fuel": MainCategory.FUEL,
        "shopping": MainCategory.SHOPPING,
        "subscriptions": MainCategory.SUBSCRIPTIONS,
    }
    return mapping.get(key, MainCategory.MISCELLANEOUS)


def default_expense_hashtags(
    main_category: str,
    sub_category: Optional[str] = None,
    *,
    vendor_name: Optional[str] = None,
    bill_name: Optional[str] = None,
    limit: int = 3,
) -> List[str]:
    """Hashtags to persist on create when the client did not send any."""
    tags = suggest_hashtags_from_ocr(
        main_category,
        sub_category,
        vendor_name=vendor_name,
        max_tags=limit,
    )
    if tags:
        return normalize_hashtags_list(tags)

    manual = to_manual_category(main_category, sub_category)
    return normalize_hashtags_list(
        get_hashtag_recommendations(manual, sub_category, limit=limit)["recommended"]
    )


def get_hashtag_recommendations(
    category: str,
    sub_category: Optional[str] = None,
    limit: int = 3,
) -> Dict[str, List[str]]:
    """Return up to 3 suggested hashtags when a category is selected."""
    manual = to_manual_category(category, sub_category)
    tags: List[str] = list(_CATEGORY_HASHTAGS.get(manual, ["#miscellaneous"]))
    if sub_category:
        extras = _SUBCATEGORY_EXTRA.get(manual, {}).get(sub_category.lower(), [])
        tags = extras + tags
    unique = normalize_hashtags_list(tags)
    recommended = unique[:limit]
    return {"category": manual, "recommended": recommended, "all": unique}


def suggest_hashtags_from_ocr(
    main_category: str,
    sub_category: Optional[str] = None,
    *,
    vendor_name: Optional[str] = None,
    extracted: Optional[Dict[str, Any]] = None,
    max_tags: int = 3,
) -> List[str]:
    """Build hashtag list after OCR scan from category + vendor signals."""
    manual = to_manual_category(main_category, sub_category)
    base = get_hashtag_recommendations(manual, sub_category, limit=max_tags)
    tags: List[str] = list(base["recommended"])
    seen = {t.lower() for t in tags}

    corpus = " ".join(
        filter(
            None,
            [
                vendor_name or "",
                (extracted or {}).get("vendor_name") or "",
                (extracted or {}).get("restaurant_name") or "",
                ((extracted or {}).get("raw_text") or "")[:2000],
            ],
        )
    ).lower()

    vendor_rules = [
        (("airtel", "bharti airtel"), ["#airtel", "#mobile", "#utilities"]),
        (("jio", "reliance jio"), ["#jio", "#mobile", "#utilities"]),
        (("bsnl",), ["#bsnl", "#mobile"]),
        (("vodafone", " vi "), ["#vi", "#mobile"]),
        (("uber",), ["#uber", "#travel"]),
        (("ola",), ["#ola", "#travel"]),
        (("rapido",), ["#rapido", "#travel"]),
        (("swiggy",), ["#swiggy", "#food", "#delivery"]),
        (("zomato",), ["#zomato", "#food", "#delivery"]),
        (("amazon",), ["#amazon", "#shopping"]),
        (("netflix",), ["#netflix", "#subscriptions"]),
        (("spotify",), ["#spotify", "#subscriptions"]),
        (("prime", "hotstar"), ["#prime", "#subscriptions"]),
    ]
    for keys, extra in vendor_rules:
        if any(k in corpus for k in keys):
            for t in extra:
                n = normalize_hashtag(t)
                if n.lower() not in seen:
                    seen.add(n.lower())
                    tags.append(n)

    if sub_category:
        sub_tag = normalize_hashtag(sub_category.replace("_", ""))
        if sub_tag.lower() not in seen:
            tags.insert(0, sub_tag)
            seen.add(sub_tag.lower())

    category_tag = normalize_hashtag(manual)
    if category_tag.lower() not in seen:
        tags.insert(0, category_tag)

    return tags[:max_tags]


def get_manual_categories_payload() -> Dict[str, Any]:
    from app.data.business_taxonomy import get_manual_categories_payload as _biz

    return _biz()


def get_manual_categories_payload_legacy() -> Dict[str, Any]:
    return {
        "main_categories": MANUAL_MAIN_CATEGORIES,
        "note": "Select a main category; use GET /categories/{category}/hashtags for AI hashtag suggestions.",
    }


# Ensure every business main category has hashtag suggestions
for _cat in MANUAL_CATEGORY_VALUES:
    if _cat not in _CATEGORY_HASHTAGS:
        _CATEGORY_HASHTAGS[_cat] = [
            f"#{_cat.replace('_', '-')}",
            "#expense",
            "#bizwy",
        ]
