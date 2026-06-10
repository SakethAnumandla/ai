"""Expense vs income and main/sub category detection for OCR bills."""
import re
from typing import Any, Dict, List, Optional, Tuple

from app.models import MainCategory, TransactionType

# (regex or substring, score weight)
_INCOME_PATTERNS: List[Tuple[str, int]] = [
    (r"\bsalary\b", 12),
    (r"pay\s*slip|payslip", 14),
    (r"\bpayroll\b", 12),
    (r"net\s*pay|gross\s*pay|basic\s*pay", 10),
    (r"\bwages\b", 10),
    (r"\bbonus\b", 9),
    (r"freelance|consulting\s*fee", 8),
    (r"rental\s*income|rent\s*received", 12),
    (r"\bdividend\b", 11),
    (r"interest\s*credited|interest\s*earned", 11),
    (r"investment\s*return|maturity\s*proceeds|redemption", 10),
    (r"\brefund\s*credited|\brefund\s*received", 9),
    (r"\breimbursement\b", 9),
    (r"credited\s*to\s*(?:your\s*)?account", 8),
    (r"\bcredit\s*(?:advice|note)\b", 8),
    (r"neft\s*cr|imps\s*cr|rtgs\s*cr|upi\s*cr", 9),
    (r"amount\s*credited|funds\s*received", 9),
    (r"payment\s*received|received\s*from", 7),
    (r"\bincome\b", 6),
    (r"gift\s*received|\bgifts\b", 6),
    (r"business\s*income|profit\s*share", 8),
]

_EXPENSE_PATTERNS: List[Tuple[str, int]] = [
    (r"tax\s*invoice", 10),
    (r"\binvoice\b", 6),
    (r"\breceipt\b", 7),
    (r"\bbill\s*no", 8),
    (r"amount\s*payable|total\s*payable|grand\s*total", 7),
    (r"\bpaid\s*to\b", 8),
    (r"\bdebit\b", 7),
    (r"\bpurchase\b", 6),
    (r"\bcgst\b|\bsgst\b|\bigst\b", 9),
    (r"sub\s*total|subtotal", 5),
    (r"table\s*no|kot\b", 8),
    (r"trip\s*details|kilomet", 9),
    (r"thank\s*you\s*for\s*(?:dining|visiting)", 7),
]

# Expense: (keywords in text/vendor, main_category, sub_category)
# Telecom/utility bills MUST be before amazon/shopping (e.g. Airtel bills mention Amazon Prime add-on).
_EXPENSE_CATEGORY_RULES: List[Tuple[List[str], MainCategory, Optional[str]]] = [
    (
        [
            "bharti airtel",
            "one airtel",
            "airtel.in",
            "airtel thanks",
            ".mairtel",
            "registered telephone",
        ],
        MainCategory.BILLS,
        "mobile",
    ),
    (
        ["airtel", "jio", "reliance jio", "vi postpaid", "vi prepaid", "vodafone", "bsnl"],
        MainCategory.BILLS,
        "mobile",
    ),
    (
        [
            "broadband",
            "wi-fi",
            "wifi",
            "fiber",
            "fibernet",
            "fixedline",
            "fixed line",
            "_dsl",
            "internet bill",
        ],
        MainCategory.BILLS,
        "internet",
    ),
    (["electricity", "water bill", "gas bill", "dth", "property tax"], MainCategory.BILLS, None),
    (["uber", "rapido", "ola", "meru", "irctc", "makemytrip", "redbus", "indigo", "spicejet"], MainCategory.TRAVEL, None),
    (["swiggy", "zomato", "dunzo", "blinkit", "zepto"], MainCategory.FOOD, None),
    (["kitchen", "restaurant", "cafe", "biryani", "dining", "dominos", "mcdonald", "kfc", "pizza", "bhagini", "curry", "tandoori"], MainCategory.FOOD, "restaurant"),
    (["petrol", "diesel", "fuel", "hpcl", "iocl", "bharat petroleum", "indian oil"], MainCategory.FUEL, "petrol"),
    (["amazon", "flipkart", "myntra", "meesho", "reliance digital", "croma"], MainCategory.SHOPPING, None),
    (["bigbasket", "dmart", "more supermarket", "grofers"], MainCategory.GROCERIES, "groceries"),
    (["apollo", "pharmacy", "medplus", "hospital", "clinic", "diagnostic"], MainCategory.HEALTHCARE, "medicine"),
    (["netflix", "hotstar", "prime video", "bookmyshow", "pvr", "inox"], MainCategory.ENTERTAINMENT, None),
    (["school", "college", "university", "tuition", "coursera", "udemy"], MainCategory.EDUCATION, None),
    (["lic ", "insurance premium", "policy premium"], MainCategory.INSURANCE, None),
    (["spotify", "youtube premium", "subscription"], MainCategory.SUBSCRIPTIONS, None),
    (["salon", "spa", "grooming"], MainCategory.PERSONAL_CARE, None),
    (["rent paid", "house rent", "monthly rent"], MainCategory.RENT, None),
]

# Income-specific category rules (checked when transaction is income)
_INCOME_CATEGORY_RULES: List[Tuple[List[str], MainCategory, str]] = [
    (["salary", "pay slip", "payslip", "payroll", "wages", "net pay"], MainCategory.SALARY, "salary_income"),
    (["bonus"], MainCategory.SALARY, "bonus"),
    (["freelance", "consulting"], MainCategory.MISCELLANEOUS, "freelance"),
    (["rental income", "rent received"], MainCategory.RENT, "rental_income"),
    (["dividend", "mutual fund", "fd maturity", "interest credited"], MainCategory.INVESTMENT, "investment_returns"),
    (["refund"], MainCategory.MISCELLANEOUS, "refund"),
    (["reimbursement"], MainCategory.MISCELLANEOUS, "reimbursement"),
    (["gift"], MainCategory.MISCELLANEOUS, "gifts"),
    (["business income", "profit share"], MainCategory.MISCELLANEOUS, "business"),
]


def _corpus(extracted: Dict[str, Any], raw_text: Optional[str] = None) -> str:
    parts: List[str] = []
    if raw_text:
        parts.append(raw_text)
    for key in ("vendor_name", "restaurant_name", "ride_type", "customer_name"):
        v = extracted.get(key)
        if v:
            parts.append(str(v))
    for item in extracted.get("items_list") or []:
        if isinstance(item, dict) and item.get("name"):
            parts.append(str(item["name"]))
    return " ".join(parts).lower()


def _score_patterns(corpus: str, patterns: List[Tuple[str, int]]) -> int:
    score = 0
    for pattern, weight in patterns:
        if re.search(pattern, corpus, re.IGNORECASE):
            score += weight
    return score


def detect_transaction_type(
    extracted: Dict[str, Any], raw_text: Optional[str] = None
) -> TransactionType:
    corpus = _corpus(extracted, raw_text)
    income = _score_patterns(corpus, _INCOME_PATTERNS)
    expense = _score_patterns(corpus, _EXPENSE_PATTERNS)

    # Strong expense receipt signals override weak income hints
    if expense >= 12 and income < expense:
        return TransactionType.EXPENSE
    if income >= 10 and income > expense + 2:
        return TransactionType.INCOME
    if income > expense + 4:
        return TransactionType.INCOME
    # Food/ride receipts are almost always expenses
    if any(
        x in corpus
        for x in (
            "kitchen",
            "restaurant",
            "uber",
            "rapido",
            "swiggy",
            "zomato",
            "cgst",
            "sgst",
            "table no",
        )
    ):
        return TransactionType.EXPENSE
    return TransactionType.EXPENSE


def detect_main_category(
    vendor_name: Optional[str],
    restaurant_name: Optional[str] = None,
    *,
    raw_text: Optional[str] = None,
    transaction_type: Optional[TransactionType] = None,
    extracted: Optional[Dict[str, Any]] = None,
) -> MainCategory:
    combined = f"{vendor_name or ''} {restaurant_name or ''}".lower()
    if raw_text:
        combined = f"{combined} {raw_text[:4000]}".lower()
    if extracted:
        combined = f"{combined} {_corpus(extracted, None)}"

    tx = transaction_type or TransactionType.EXPENSE
    if tx == TransactionType.INCOME:
        for keywords, main_cat, _sub in _INCOME_CATEGORY_RULES:
            if any(k in combined for k in keywords):
                return main_cat
        return MainCategory.SALARY if any(k in combined for k in ("salary", "payroll", "wages")) else MainCategory.MISCELLANEOUS

    for keywords, main_cat, _sub in _EXPENSE_CATEGORY_RULES:
        if any(k in combined for k in keywords):
            return main_cat

    travel_signals = (
        "uber",
        "rapido",
        "ola",
        "trip",
        "kilomet",
        "flight",
        "airline",
        "airport",
        "irctc",
        "hotel",
        "lodging",
        "accommodation",
        "makemytrip",
        "redbus",
        "toll",
        "parking",
        "outstation",
        "business trip",
    )
    if any(x in combined for x in travel_signals):
        return MainCategory.TRAVEL
    if any(
        x in combined
        for x in (
            "swiggy",
            "zomato",
            "kitchen",
            "restaurant",
            "cafe",
            "biryani",
            "dining",
            "food",
        )
    ):
        return MainCategory.FOOD
    if any(x in combined for x in ("electricity", "water", "gas", "internet", "mobile", "dth")):
        return MainCategory.BILLS
    return MainCategory.MISCELLANEOUS


def category_confident(
    main_category: MainCategory,
    sub_category: Optional[str],
    *,
    extracted: Optional[Dict[str, Any]] = None,
    raw_text: Optional[str] = None,
) -> bool:
    """True when rules matched a specific category (not the generic fallback)."""
    if main_category != MainCategory.MISCELLANEOUS:
        return True
    if sub_category:
        return True
    from app.data.business_taxonomy import suggest_categories_from_text

    corpus = ""
    if extracted:
        corpus = _corpus(extracted, raw_text)
    hinted = suggest_categories_from_text(corpus)
    return bool(hinted.get("main_category"))


def detect_sub_category(
    vendor_name: Optional[str],
    main_category: MainCategory,
    *,
    raw_text: Optional[str] = None,
    transaction_type: Optional[TransactionType] = None,
    extracted: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    combined = (vendor_name or "").lower()
    if raw_text:
        combined = f"{combined} {raw_text[:2000]}".lower()
    if extracted:
        combined = f"{combined} {_corpus(extracted, None)}"

    tx = transaction_type or TransactionType.EXPENSE
    if tx == TransactionType.INCOME:
        for keywords, _main, sub in _INCOME_CATEGORY_RULES:
            if any(k in combined for k in keywords):
                return sub
        return "salary_income" if main_category == MainCategory.SALARY else None

    for keywords, main_cat, sub in _EXPENSE_CATEGORY_RULES:
        if main_cat == main_category and sub and any(k in combined for k in keywords):
            return sub

    if main_category == MainCategory.TRAVEL:
        from app.data.business_taxonomy import _has_food_signals, _has_travel_context

        if _has_travel_context(combined) and _has_food_signals(combined):
            if any(x in combined for x in ("airport", "in-flight", "in flight", "transit")):
                return "food_during_travel"
            if any(x in combined for x in ("hotel", "room service", "lodging", "resort")):
                return "food_during_travel"
            return "food_during_travel"
        if any(x in combined for x in ("hotel", "lodging", "accommodation", "resort", "inn")):
            return "accommodation"
        v = (vendor_name or "").lower()
        if "uber" in v or "uber" in combined:
            return "uber"
        if "rapido" in v or "rapido" in combined:
            return "rapido"
        if "ola" in v or "ola" in combined:
            return "ola"
        if any(x in combined for x in ("flight", "airline", "airport")):
            return "flight"
        return "taxi"

    if main_category == MainCategory.FOOD:
        if "swiggy" in combined:
            return "swiggy"
        if "zomato" in combined:
            return "zomato"
        if any(x in combined for x in ("kitchen", "restaurant", "cafe", "dining")):
            return "restaurant"
        return "dining"

    if main_category == MainCategory.FUEL:
        if "diesel" in combined:
            return "diesel"
        if "cng" in combined:
            return "cng"
        return "petrol"

    if main_category == MainCategory.SHOPPING:
        if "amazon" in combined:
            return "electronics"
        if "myntra" in combined:
            return "clothing"
        return None

    if main_category == MainCategory.ENTERTAINMENT:
        if "netflix" in combined:
            return "netflix"
        if "hotstar" in combined:
            return "hotstar"
        if "prime" in combined:
            return "amazon_prime"

    if main_category == MainCategory.BILLS:
        if any(
            x in combined
            for x in (
                "wi-fi",
                "wifi",
                "broadband",
                "fiber",
                "fibernet",
                "fixedline",
                "fixed line",
                "_dsl",
                "internet bill",
            )
        ):
            return "internet"
        if any(
            x in combined
            for x in (
                "airtel",
                "jio",
                "bsnl",
                "vodafone",
                "postpaid",
                "prepaid",
                "mobile",
                "rtn",
                "one airtel",
            )
        ):
            return "mobile"
        if "electricity" in combined:
            return "electricity"
        if "water" in combined:
            return "water"
        if "dth" in combined:
            return "dth"

    return None


def classify_bill(
    extracted: Dict[str, Any], raw_text: Optional[str] = None
) -> Dict[str, Any]:
    """
    Classify OCR output as income or expense with main/sub category.
    Mutates nothing; returns fields to merge into extracted dict.
    """
    corpus = _corpus(extracted, raw_text)
    income_score = _score_patterns(corpus, _INCOME_PATTERNS)
    expense_score = _score_patterns(corpus, _EXPENSE_PATTERNS)

    transaction_type = detect_transaction_type(extracted, raw_text)
    main_category = detect_main_category(
        extracted.get("vendor_name"),
        extracted.get("restaurant_name"),
        raw_text=raw_text,
        transaction_type=transaction_type,
        extracted=extracted,
    )
    sub_category = detect_sub_category(
        extracted.get("vendor_name"),
        main_category,
        raw_text=raw_text,
        transaction_type=transaction_type,
        extracted=extracted,
    )

    # Classification confidence from signal strength
    if transaction_type == TransactionType.INCOME:
        signal = income_score
        gap = income_score - expense_score
    else:
        signal = expense_score
        gap = expense_score - income_score
    confidence = min(100.0, 40.0 + signal * 3.0 + max(0, gap) * 4.0)
    if main_category != MainCategory.MISCELLANEOUS:
        confidence = min(100.0, confidence + 10.0)
    if sub_category:
        confidence = min(100.0, confidence + 5.0)

    return {
        "transaction_type": transaction_type.value,
        "main_category": main_category.value,
        "sub_category": sub_category,
        "classification_confidence": round(confidence, 1),
        "income_score": income_score,
        "expense_score": expense_score,
    }


def resolve_classification(
    extracted: Dict[str, Any], raw_text: Optional[str] = None
) -> Tuple[TransactionType, MainCategory, Optional[str]]:
    """Use OCR-embedded classification when valid, else classify from text."""
    from app.data.business_taxonomy import classify_taxonomy_from_scan
    from app.utils.category_hashtags import main_category_from_manual

    scan_source = dict(extracted)
    if raw_text:
        scan_source.setdefault("raw_text", raw_text)
    business = classify_taxonomy_from_scan(scan_source)
    if business.get("main_category"):
        tx = detect_transaction_type(extracted, raw_text)
        mc = main_category_from_manual(business["main_category"])
        return tx, mc, business.get("sub_category")

    tt_raw = extracted.get("transaction_type")
    mc_raw = extracted.get("main_category")
    if tt_raw and mc_raw:
        try:
            tt = TransactionType(tt_raw if isinstance(tt_raw, str) else tt_raw.value)
            mc = MainCategory(mc_raw if isinstance(mc_raw, str) else mc_raw.value)
            sub = extracted.get("sub_category")
            return tt, mc, sub
        except ValueError:
            pass

    result = classify_bill(extracted, raw_text)
    return (
        TransactionType(result["transaction_type"]),
        MainCategory(result["main_category"]),
        result.get("sub_category"),
    )


def default_bill_name(
    extracted: dict,
    file_name: str,
    bill_index: Optional[int] = None,
    *,
    transaction_type: Optional[TransactionType] = None,
) -> str:
    vendor = extracted.get("restaurant_name") or extracted.get("vendor_name")
    tx = transaction_type
    if tx is None and extracted.get("transaction_type"):
        try:
            tx = TransactionType(extracted["transaction_type"])
        except ValueError:
            tx = None

    if vendor:
        name = str(vendor).strip()
    else:
        name = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
        name = name[:200]

    if tx == TransactionType.INCOME:
        prefix = "Income"
        if extracted.get("sub_category") == "salary_income":
            prefix = "Salary"
        elif extracted.get("sub_category") == "bonus":
            prefix = "Bonus"
        name = f"{prefix} — {name}" if vendor else f"{prefix} ({name})"

    if bill_index is not None:
        return f"Bill {bill_index} — {name}"
    return name
