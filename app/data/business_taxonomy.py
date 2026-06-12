"""
Business expense taxonomy (main → sub → line item) with GST/ITC/approval metadata.
Reference: company expense classification spreadsheet.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# EUR monthly budget target (wallet utilisation)
DEFAULT_MONTHLY_BUDGET_EUR = 1_000_000.0
# Amount-based approval tiers (EUR): L1 only below 10K, 2 levels 10K–100K, 3 levels above 100K
L1_ONLY_APPROVAL_THRESHOLD_EUR = 10_000.0
THREE_LEVEL_APPROVAL_THRESHOLD_EUR = 100_000.0
# Back-compat alias
CEO_ONLY_APPROVAL_THRESHOLD_EUR = THREE_LEVEL_APPROVAL_THRESHOLD_EUR
DEFAULT_CURRENCY = "EUR"

# Allowed financial years for bill dates (Apr–Mar)
ALLOWED_FINANCIAL_YEARS = ("FY2025-26", "FY2026-27")


def _li(
    value: str,
    label: str,
    *,
    gst: Optional[str] = None,
    itc: str = "No",
    approval: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "value": value,
        "label": label,
        "gst_pct": gst,
        "itc_eligible": itc,
        "approval_roles": approval or ["Manager"],
        "notes": notes,
    }


NONE_SUB_VALUE = "none"
OTHERS_SUB_VALUE = "others"
NONE_LINE_VALUE = "none"
OTHERS_LINE_VALUE = "others"


def _none_line_item() -> Dict[str, Any]:
    return _li(NONE_LINE_VALUE, "None", gst=None, approval=["Manager"])


def _others_line_item() -> Dict[str, Any]:
    return _li(
        OTHERS_LINE_VALUE,
        "Others (specify in vendor or notes)",
        gst="Varies",
        itc="Varies",
        approval=["Manager"],
    )


def _none_subcategory() -> Dict[str, Any]:
    return {"value": NONE_SUB_VALUE, "label": "None", "line_items": []}


def _others_subcategory() -> Dict[str, Any]:
    return {
        "value": OTHERS_SUB_VALUE,
        "label": "Others",
        "line_items": [_others_line_item()],
    }


def _enrich_line_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values = {item["value"] for item in items}
    out = list(items)
    if NONE_LINE_VALUE not in values:
        out.append(_none_line_item())
    if OTHERS_LINE_VALUE not in values:
        out.append(_others_line_item())
    return out


def _enrich_subcategories(subs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values = {sub["value"] for sub in subs}
    out: List[Dict[str, Any]] = []
    if NONE_SUB_VALUE not in values:
        out.append(_none_subcategory())
    out.extend(subs)
    if OTHERS_SUB_VALUE not in values:
        out.append(_others_subcategory())
    for sub in out:
        sub["line_items"] = _enrich_line_items(sub.get("line_items") or [])
    return out


BUSINESS_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "people_hr": {
        "label": "People & HR Costs",
        "icon": "👥",
        "color": "#1565C0",
        "subcategories": {
            "salaries_wages": {
                "label": "Salaries & Wages",
                "line_items": [
                    _li("regular_salaries", "Regular Salaries", gst="No", approval=["Manager", "HOD", "HR"]),
                    _li("contract_freelance", "Contract / Freelance", gst="No", approval=["Manager", "HOD", "HR"], notes="TDS @ 10% may apply"),
                ],
            },
            "employee_benefits": {
                "label": "Employee Benefits",
                "line_items": [
                    _li("health_insurance", "Health Insurance", gst="18%", itc="No", approval=["HR", "Finance"]),
                    _li("provident_fund", "Provident Fund / ESI", gst="No", approval=["HR", "Finance"]),
                ],
            },
            "recruitment": {
                "label": "Recruitment",
                "line_items": [
                    _li("job_portals", "Job Portal Subscriptions", gst="18%", itc="Yes", approval=["HR", "Manager"]),
                    _li("recruitment_agency", "Recruitment Agency Fees", gst="18%", itc="Yes", approval=["HR", "Director"]),
                ],
            },
            "training_development": {
                "label": "Training & Development",
                "line_items": [
                    _li("external_courses", "External Courses", gst="18%", itc="Yes", approval=["Manager", "HR"]),
                ],
            },
            "staff_welfare": {
                "label": "Staff Welfare",
                "line_items": [
                    _li("team_meals", "Team Meals & Outings", gst="5%", itc="No", approval=["Manager", "HOD"]),
                    _li("employee_gifts", "Employee Gifts & Rewards", gst="18%", itc="No", approval=["HR", "Director"]),
                ],
            },
        },
    },
    "office_facilities": {
        "label": "Office & Facilities",
        "icon": "🏢",
        "color": "#2E7D32",
        "subcategories": {
            "rent_lease": {
                "label": "Rent & Lease",
                "line_items": [
                    _li("office_rent", "Office Rent", gst="18%", itc="Yes", approval=["Director", "Admin"]),
                    _li("warehouse_rent", "Warehouse Rent", gst="18%", itc="Yes", approval=["Director", "Admin"]),
                ],
            },
            "utilities": {
                "label": "Utilities",
                "line_items": [
                    _li("electricity", "Electricity", gst="18%", itc="Yes", approval=["Admin"]),
                    _li("internet_broadband", "Internet & Broadband", gst="18%", itc="Yes", approval=["Admin", "IT"]),
                    _li("telephone", "Telephone / Landline", gst="18%", itc="Yes", approval=["Admin"]),
                ],
            },
            "office_supplies": {
                "label": "Office Supplies",
                "line_items": [
                    _li("stationery", "Stationery & Printing", gst="12%", itc="Yes", approval=["Admin"]),
                    _li("pantry", "Pantry Supplies", gst="5%", itc="Yes", approval=["Admin"]),
                ],
            },
            "office_maintenance": {
                "label": "Office Maintenance",
                "line_items": [
                    _li("repairs", "Repairs & Maintenance", gst="18%", itc="Yes", approval=["Admin", "Director"]),
                    _li("housekeeping", "Housekeeping Services", gst="18%", itc="Yes", approval=["Admin"]),
                ],
            },
            "furniture": {
                "label": "Furniture Purchase",
                "line_items": [
                    _li("furniture_purchase", "Furniture Purchase", gst="18%", itc="Yes", approval=["Director", "Admin"], notes="Capitalise if > €5,000"),
                ],
            },
        },
    },
    "technology_it": {
        "label": "Technology & IT",
        "icon": "💻",
        "color": "#6A1B9A",
        "subcategories": {
            "hardware": {
                "label": "Hardware",
                "line_items": [
                    _li("laptops", "Laptops & Desktops", gst="18%", itc="Yes", approval=["IT", "HOD"], notes="Capitalise if > €5,000"),
                    _li("mobile_devices", "Mobile Phones & Tablets", gst="18%", itc="Yes", approval=["IT", "Director"]),
                ],
            },
            "software_subscriptions": {
                "label": "Software & Subscriptions",
                "line_items": [
                    _li("productivity_tools", "Productivity Tools (O365, GSuite)", gst="18%", itc="Yes", approval=["IT", "Finance"]),
                    _li("accounting_software", "Accounting Software", gst="18%", itc="Yes", approval=["Finance", "Director"]),
                    _li("crm_erp", "CRM / ERP Subscriptions", gst="18%", itc="Yes", approval=["IT", "Director"]),
                ],
            },
            "it_services": {
                "label": "IT Services",
                "line_items": [
                    _li("it_support_amc", "IT Support & AMC", gst="18%", itc="Yes", approval=["IT", "Finance"]),
                    _li("cloud_hosting", "Cloud Hosting & Servers", gst="18%", itc="Yes", approval=["IT", "Director"]),
                    _li("cybersecurity", "Cybersecurity Services", gst="18%", itc="Yes", approval=["IT", "Director"]),
                ],
            },
            "telecom_mobile": {
                "label": "Telecom & Mobile",
                "line_items": [
                    _li("mobile_recharge", "Mobile Recharges", gst="18%", itc="Yes", approval=["IT", "Admin"]),
                    _li("roaming", "Roaming Charges", gst="18%", itc="Yes", approval=["Manager", "IT"]),
                ],
            },
        },
    },
    "travel_transportation": {
        "label": "Travel & Transportation",
        "icon": "✈️",
        "color": "#0277BD",
        "subcategories": {
            "domestic_travel": {
                "label": "Domestic Travel",
                "line_items": [
                    _li("airfare_domestic", "Airfare (Domestic)", gst="5%", itc="Yes", approval=["Manager", "Director"]),
                    _li("train_bus", "Train / Bus Tickets", gst="5%", itc="Yes", approval=["Manager"]),
                    _li("local_cab", "Local Cab / Taxi", gst="5%", itc="No", approval=["Manager"]),
                ],
            },
            "international_travel": {
                "label": "International Travel",
                "line_items": [
                    _li("airfare_intl", "Airfare (International)", gst="5%", itc="Yes", approval=["Director"]),
                    _li("visa_fees", "Visa Fees", gst="No", itc="No", approval=["Manager", "Admin"]),
                ],
            },
            "accommodation": {
                "label": "Accommodation",
                "line_items": [
                    _li("hotel_domestic", "Hotel (Domestic)", gst="12%", itc="Yes", approval=["Manager", "Director"]),
                    _li("hotel_intl", "Hotel (International)", gst="12%", itc="Yes", approval=["Director"]),
                ],
            },
            "vehicle_expenses": {
                "label": "Vehicle Expenses",
                "line_items": [
                    _li("fuel_reimbursement", "Fuel Reimbursement", gst="18%", itc="No", approval=["Manager", "Admin"]),
                    _li("vehicle_maintenance", "Vehicle Maintenance", gst="18%", itc="Yes", approval=["Admin", "Ops"]),
                ],
            },
            "food_during_travel": {
                "label": "Food During Travel",
                "line_items": [
                    _li("restaurant_dining", "Restaurant / Dining", gst="5%", itc="No", approval=["Manager"]),
                    _li("airport_transit_meals", "Airport / In-transit Meals", gst="5%", itc="No", approval=["Manager"]),
                    _li("hotel_food", "Hotel Food & Room Service", gst="5%", itc="No", approval=["Manager", "Director"]),
                    _li("snacks_beverages", "Snacks & Beverages", gst="5%", itc="No", approval=["Manager"]),
                ],
            },
            "entertainment_during_travel": {
                "label": "Food & Entertainment",
                "line_items": [
                    _li("client_meals_travel", "Client Meals on Trip", gst="5%", itc="No", approval=["Manager", "Director"]),
                    _li("team_meals_travel", "Team Meals on Trip", gst="5%", itc="No", approval=["Manager", "HOD"]),
                    _li("events_activities", "Events & Activities", gst="18%", itc="No", approval=["Manager", "Director"]),
                    _li("recreation_sightseeing", "Recreation / Sightseeing", gst="18%", itc="No", approval=["Manager"]),
                ],
            },
        },
    },
    "meals_entertainment": {
        "label": "Meals & Entertainment",
        "icon": "🍽️",
        "color": "#E65100",
        "subcategories": {
            "business_meals": {
                "label": "Business Meals",
                "line_items": [
                    _li("client_entertainment", "Client Entertainment", gst="5%", itc="No", approval=["Manager", "HOD"]),
                    _li("working_lunches", "Working Lunches", gst="5%", itc="No", approval=["Manager", "HOD"]),
                ],
            },
            "client_hospitality": {
                "label": "Client Hospitality",
                "line_items": [
                    _li("client_gifts", "Client Gifts", gst="18%", itc="No", approval=["Manager", "Director"]),
                ],
            },
            "internal_events": {
                "label": "Internal Events",
                "line_items": [
                    _li("corporate_events", "Corporate Events", gst="18%", itc="No", approval=["HOD", "Director"]),
                    _li("team_offsite", "Team Offsite / Retreats", gst="18%", itc="No", approval=["Director", "HR"]),
                ],
            },
        },
    },
    "sales_marketing": {
        "label": "Sales & Marketing",
        "icon": "📣",
        "color": "#00897B",
        "subcategories": {
            "advertising": {
                "label": "Advertising",
                "line_items": [
                    _li("digital_ads", "Digital Advertising", gst="18%", itc="Yes", approval=["Marketing", "Director"]),
                    _li("print_outdoor", "Print / Outdoor Ads", gst="18%", itc="Yes", approval=["Marketing"]),
                ],
            },
            "website_digital": {
                "label": "Website & Digital",
                "line_items": [
                    _li("website_dev", "Website Development", gst="18%", itc="Yes", approval=["Marketing", "IT"]),
                    _li("seo_sem", "SEO / SEM Services", gst="18%", itc="Yes", approval=["Marketing"]),
                ],
            },
            "marketing_collateral": {
                "label": "Marketing Collateral",
                "line_items": [
                    _li("brochures", "Brochures & Printing", gst="12%", itc="Yes", approval=["Marketing"]),
                    _li("merchandise", "Branded Merchandise", gst="18%", itc="Yes", approval=["Marketing", "Director"]),
                ],
            },
        },
    },
    "professional_legal": {
        "label": "Professional & Legal",
        "icon": "⚖️",
        "color": "#4E342E",
        "subcategories": {
            "legal": {
                "label": "Legal",
                "line_items": [
                    _li("legal_retainer", "Legal Retainer", gst="18%", itc="Yes", approval=["Director", "Finance"]),
                    _li("trademark", "Trademark Registration", gst="18%", itc="Yes", approval=["Director"]),
                ],
            },
            "accounting_finance": {
                "label": "Accounting & Finance",
                "line_items": [
                    _li("audit_fees", "Audit Fees", gst="18%", itc="Yes", approval=["Finance", "Director"]),
                    _li("tax_filing", "Tax Filing", gst="18%", itc="Yes", approval=["Finance"]),
                ],
            },
            "consulting": {
                "label": "Consulting",
                "line_items": [
                    _li("business_advisory", "Business Advisory", gst="18%", itc="Yes", approval=["Director"]),
                    _li("it_consulting", "IT Consulting", gst="18%", itc="Yes", approval=["IT", "Director"]),
                ],
            },
        },
    },
    "finance_banking": {
        "label": "Finance & Banking",
        "icon": "🏦",
        "color": "#C62828",
        "subcategories": {
            "banking_charges": {
                "label": "Banking Charges",
                "line_items": [
                    _li("bank_charges", "Bank Transaction Charges", gst="18%", itc="Yes", approval=["Finance"]),
                    _li("account_maintenance", "Account Maintenance", gst="18%", itc="Yes", approval=["Finance"]),
                ],
            },
            "payment_gateway": {
                "label": "Payment Gateway",
                "line_items": [
                    _li("pg_fees", "Transaction Fees", gst="18%", itc="Yes", approval=["Finance"]),
                ],
            },
            "insurance": {
                "label": "Insurance",
                "line_items": [
                    _li("property_insurance", "Property Insurance", gst="18%", itc="Yes", approval=["Finance", "Director"]),
                    _li("professional_indemnity", "Professional Indemnity", gst="18%", itc="Yes", approval=["Director"]),
                ],
            },
        },
    },
    "operations_supply": {
        "label": "Operations & Supply Chain",
        "icon": "📦",
        "color": "#5D4037",
        "subcategories": {
            "raw_materials": {
                "label": "Raw Materials",
                "line_items": [
                    _li("raw_material", "Raw Material Purchase", gst="18%", itc="Yes", approval=["Purchase", "Ops"]),
                    _li("packaging", "Packaging Material", gst="18%", itc="Yes", approval=["Purchase"]),
                ],
            },
            "logistics": {
                "label": "Logistics",
                "line_items": [
                    _li("freight", "Outbound / Inbound Freight", gst="12%", itc="Yes", approval=["Ops", "Purchase"]),
                    _li("customs", "Customs & Clearing", gst="18%", itc="Yes", approval=["Ops", "Finance"]),
                ],
            },
        },
    },
    "taxes_govt": {
        "label": "Taxes & Govt Dues",
        "icon": "🏛️",
        "color": "#37474F",
        "subcategories": {
            "direct_taxes": {
                "label": "Direct Taxes",
                "line_items": [
                    _li("tds_tcs", "TDS / TCS Remittances", gst="No", itc="No", approval=["Finance"]),
                ],
            },
            "indirect_taxes": {
                "label": "Indirect Taxes",
                "line_items": [
                    _li("gst_payments", "GST Payments", gst="No", itc="No", approval=["Finance"]),
                ],
            },
        },
    },
    "miscellaneous": {
        "label": "Miscellaneous",
        "icon": "📋",
        "color": "#757575",
        "subcategories": {
            "general": {
                "label": "General",
                "line_items": [
                    _li("postage_courier", "Postage & Courier", gst="18%", itc="Yes", approval=["Admin"]),
                    _li("petty_cash", "Petty Cash Expenses", gst="Varies", itc="Varies", approval=["Admin", "Finance"]),
                    _li("unclassified", "Unclassified / To Review", gst="Varies", itc="Varies", approval=["Finance", "Director"]),
                ],
            },
        },
    },
}

# Legacy consumer categories → business main (for OCR / old data)
LEGACY_MAIN_TO_BUSINESS: Dict[str, str] = {
    "travel": "travel_transportation",
    "food": "meals_entertainment",
    "bills": "office_facilities",
    "utilities": "office_facilities",
    "fuel": "travel_transportation",
    "shopping": "miscellaneous",
    "subscriptions": "technology_it",
    "entertainment": "meals_entertainment",
    "healthcare": "people_hr",
    "education": "people_hr",
    "insurance": "finance_banking",
    "rent": "office_facilities",
    "salary": "people_hr",
    "miscellaneous": "miscellaneous",
}


def get_taxonomy_hierarchy() -> Dict[str, Any]:
    """Full tree for GET /categories/hierarchy and manual entry."""
    mains = []
    for key, meta in BUSINESS_TAXONOMY.items():
        subs = []
        for sub_key, sub_meta in meta.get("subcategories", {}).items():
            subs.append({
                "value": sub_key,
                "label": sub_meta["label"],
                "line_items": sub_meta.get("line_items", []),
            })
        mains.append({
            "value": key,
            "label": meta["label"],
            "icon": meta.get("icon", ""),
            "color": meta.get("color", "#607D8B"),
            "subcategories": _enrich_subcategories(subs),
        })

    main_values = {m["value"] for m in mains}
    if OTHERS_SUB_VALUE not in main_values:
        mains.append({
            "value": OTHERS_SUB_VALUE,
            "label": "Others",
            "icon": "📌",
            "color": "#9E9E9E",
            "subcategories": _enrich_subcategories([
                {
                    "value": "general",
                    "label": "General",
                    "line_items": [
                        _li(
                            OTHERS_LINE_VALUE,
                            "Others (describe in vendor or notes)",
                            gst="Varies",
                            itc="Varies",
                            approval=["Manager", "Finance"],
                        ),
                    ],
                },
            ]),
        })

    return {
        "currency": DEFAULT_CURRENCY,
        "monthly_budget_target": DEFAULT_MONTHLY_BUDGET_EUR,
        "financial_years": list(ALLOWED_FINANCIAL_YEARS),
        "main_categories": mains,
    }


def get_manual_categories_payload() -> Dict[str, Any]:
    hierarchy = get_taxonomy_hierarchy()
    return {
        "categories": [
            {
                "value": m["value"],
                "label": m["label"],
                "icon": m.get("icon", ""),
                "color": m.get("color", ""),
            }
            for m in hierarchy["main_categories"]
        ],
        "hierarchy": hierarchy,
    }


def resolve_approval_roles(
    main: Optional[str],
    sub: Optional[str] = None,
    line_item: Optional[str] = None,
) -> List[str]:
    """Map taxonomy metadata to approver role keys (manager, hod, …)."""
    mapping = {
        "Manager": "manager",
        "HOD": "hod",
        "HR": "hr",
        "Director": "director",
        "Finance": "finance",
        "Admin": "admin",
        "IT": "it",
        "Marketing": "marketing",
        "Purchase": "purchase",
        "Ops": "ops",
        "CEO": "ceo",
    }
    meta = resolve_line_item_meta(main, sub, line_item)
    if meta and meta.get("approval_roles"):
        out: List[str] = []
        for r in meta["approval_roles"]:
            key = mapping.get(r, r.lower())
            if key not in out:
                out.append(key)
        return out or ["manager"]

    main_key = (main or "").lower().strip()
    tree = BUSINESS_TAXONOMY.get(main_key, {})
    sub_key = (sub or "").lower().strip()
    sub_node = tree.get("subcategories", {}).get(sub_key) if sub_key else None
    if sub_node:
        best: List[str] = []
        for item in sub_node.get("line_items", []):
            roles = item.get("approval_roles") or ["Manager"]
            mapped = [mapping.get(r, r.lower()) for r in roles]
            if len(mapped) > len(best):
                best = mapped
        if best:
            return best

    return ["manager", "hod"]


def approval_roles_for_amount(
    taxonomy_roles: List[str],
    amount: float,
) -> List[str]:
    """
    Cap approval chain by bill amount:
    - Below €10,000 → L1 only (1 level)
    - €10,000 to €99,999.99 → 2 levels (L1 + L2)
    - €100,000 and above → 3 levels (L1 + L2 + L3)
    """
    roles = [r.lower() for r in (taxonomy_roles or []) if r]
    if not roles:
        roles = ["manager", "hod"]

    if amount < L1_ONLY_APPROVAL_THRESHOLD_EUR:
        return roles[:1] if roles else ["manager"]

    if amount < THREE_LEVEL_APPROVAL_THRESHOLD_EUR:
        two: List[str] = []
        for candidate in roles + ["manager", "hod"]:
            if candidate not in two:
                two.append(candidate)
            if len(two) >= 2:
                break
        return two[:2]

    three: List[str] = []
    for candidate in roles + ["manager", "hod", "ceo"]:
        if candidate not in three:
            three.append(candidate)
        if len(three) >= 3:
            break
    return three[:3]


def find_line_item_in_taxonomy(line_item: str) -> Optional[Dict[str, str]]:
    """Locate canonical main/sub for a line-item value anywhere in the hierarchy."""
    li_key = (line_item or "").lower().strip()
    if not li_key:
        return None
    for main_key, tree in BUSINESS_TAXONOMY.items():
        for sub_key, sub_node in tree.get("subcategories", {}).items():
            for item in sub_node.get("line_items", []):
                if item["value"] == li_key:
                    return {
                        "main_category": main_key,
                        "sub_category": sub_key,
                        "line_item": li_key,
                    }
    return None


def normalize_taxonomy_fields(
    main_category: Optional[str],
    sub_category: Optional[str] = None,
    line_item: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """
    Align main/sub/line_item when the UI sends legacy main_category with hierarchy line items.
    Line item is authoritative when it exists in BUSINESS_TAXONOMY.
    """
    main = (main_category or "").lower().strip()
    sub = (sub_category or "").lower().strip() or None
    li = (line_item or "").lower().strip() or None

    if li:
        located = find_line_item_in_taxonomy(li)
        if located:
            return located

    business_main = LEGACY_MAIN_TO_BUSINESS.get(main, main)
    if li and sub and resolve_line_item_meta(business_main, sub, li):
        return {"main_category": business_main, "sub_category": sub, "line_item": li}
    if sub and business_main in BUSINESS_TAXONOMY:
        subs = BUSINESS_TAXONOMY[business_main].get("subcategories", {})
        if sub in subs:
            return {"main_category": business_main, "sub_category": sub, "line_item": li}

    stored_main = business_main if business_main in BUSINESS_TAXONOMY else main
    return {"main_category": stored_main or None, "sub_category": sub, "line_item": li}


def resolve_line_item_meta(
    main: str, sub: Optional[str], line_item: Optional[str]
) -> Optional[Dict[str, Any]]:
    main_key = (main or "").lower().strip()
    sub_key = (sub or "").lower().strip()
    li_key = (line_item or "").lower().strip()
    if not li_key:
        return None

    def _lookup(mk: str, sk: str) -> Optional[Dict[str, Any]]:
        tree = BUSINESS_TAXONOMY.get(mk, {})
        sub_node = tree.get("subcategories", {}).get(sk)
        if not sub_node:
            return None
        for item in sub_node.get("line_items", []):
            if item["value"] == li_key:
                return item
        return None

    hit = _lookup(main_key, sub_key)
    if hit:
        return hit
    mapped = LEGACY_MAIN_TO_BUSINESS.get(main_key)
    if mapped and mapped != main_key:
        hit = _lookup(mapped, sub_key)
        if hit:
            return hit
    located = find_line_item_in_taxonomy(li_key)
    if located:
        return _lookup(located["main_category"], located["sub_category"])
    return None


# Travel context on receipts (ride, flight, hotel, trip wording)
_TRAVEL_CONTEXT_KEYWORDS: List[str] = [
    "uber",
    "ola",
    "rapido",
    "meru",
    "cab",
    "taxi",
    "flight",
    "airline",
    "airport",
    "irctc",
    "makemytrip",
    "redbus",
    "indigo",
    "spicejet",
    "goibibo",
    "trip",
    "kilomet",
    "kilometer",
    "boarding pass",
    "check-in",
    "check in",
    "hotel",
    "lodging",
    "accommodation",
    "inn",
    "resort",
    "travel",
    "outstation",
    "business trip",
    "toll",
    "parking",
    "train",
    "metro",
    "bus ticket",
]

_FOOD_VENDOR_KEYWORDS: List[str] = [
    "restaurant",
    "swiggy",
    "zomato",
    "dining",
    "cafe",
    "kitchen",
    "biryani",
    "biriyani",
    "tandoori",
    "food",
    "meal",
    "lunch",
    "dinner",
    "breakfast",
    "dhaba",
    "eatery",
]

# Keywords on scanned line-item names (food receipts, etc.)
_SCAN_LINE_ITEM_KEYWORDS: List[str] = [
    "chicken",
    "mutton",
    "fish",
    "prawn",
    "curry",
    "biryani",
    "biriyani",
    "rice",
    "naan",
    "roti",
    "paratha",
    "dosa",
    "idli",
    "thali",
    "meal",
    "lunch",
    "dinner",
    "breakfast",
    "snack",
    "starter",
    "appetizer",
    "soup",
    "salad",
    "dessert",
    "beverage",
    "coffee",
    "tea",
    "juice",
    "soft drink",
    "kitchen",
    "tandoori",
    "paneer",
    "veg",
    "non-veg",
]


def _has_travel_context(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _TRAVEL_CONTEXT_KEYWORDS)


def _has_food_signals(text: str, item_names: Optional[List[str]] = None) -> bool:
    t = (text or "").lower()
    if any(k in t for k in _FOOD_VENDOR_KEYWORDS):
        return True
    if item_names:
        items = " ".join(item_names).lower()
        return any(k in items for k in _SCAN_LINE_ITEM_KEYWORDS)
    return any(k in t for k in _SCAN_LINE_ITEM_KEYWORDS)


def _classify_travel_receipt(text: str) -> Optional[Dict[str, Optional[str]]]:
    """Map travel-context receipts to business travel taxonomy."""
    t = (text or "").lower()
    if not _has_travel_context(t):
        return None

    if any(k in t for k in ("movie", "concert", "sightseeing", "activity", "event", "entertainment")):
        return {
            "main_category": "travel_transportation",
            "sub_category": "entertainment_during_travel",
            "line_item": "events_activities",
        }
    if _has_food_signals(t):
        if any(k in t for k in ("airport", "in-flight", "in flight", "transit")):
            return {
                "main_category": "travel_transportation",
                "sub_category": "food_during_travel",
                "line_item": "airport_transit_meals",
            }
        if any(k in t for k in ("hotel", "room service", "lodging", "resort", "inn")):
            return {
                "main_category": "travel_transportation",
                "sub_category": "food_during_travel",
                "line_item": "hotel_food",
            }
        return {
            "main_category": "travel_transportation",
            "sub_category": "food_during_travel",
            "line_item": "restaurant_dining",
        }
    if any(k in t for k in ("hotel", "lodging", "accommodation", "resort", "inn")):
        return {
            "main_category": "travel_transportation",
            "sub_category": "accommodation",
            "line_item": "hotel_domestic",
        }
    if any(k in t for k in ("international", "visa", "passport")):
        return {
            "main_category": "travel_transportation",
            "sub_category": "international_travel",
            "line_item": "airfare_intl",
        }
    if any(k in t for k in ("flight", "airline", "airport", "indigo", "spicejet")):
        return {
            "main_category": "travel_transportation",
            "sub_category": "domestic_travel",
            "line_item": "airfare_domestic",
        }
    if any(k in t for k in ("uber", "ola", "rapido", "cab", "taxi", "auto")):
        return {
            "main_category": "travel_transportation",
            "sub_category": "domestic_travel",
            "line_item": "local_cab",
        }
    if any(k in t for k in ("train", "irctc", "metro", "bus")):
        return {
            "main_category": "travel_transportation",
            "sub_category": "domestic_travel",
            "line_item": "train_bus",
        }
    if any(k in t for k in ("fuel", "petrol", "diesel", "toll", "parking")):
        return {
            "main_category": "travel_transportation",
            "sub_category": "vehicle_expenses",
            "line_item": "fuel_reimbursement",
        }
    return {
        "main_category": "travel_transportation",
        "sub_category": "domestic_travel",
        "line_item": "local_cab",
    }


def classify_taxonomy_from_scan(extracted: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Classify business taxonomy (main → sub → line item) from OCR at scan time.
    Prioritises line items, then vendor/bill name. Returns nulls when uncertain.
    """
    item_names: List[str] = []
    for row in extracted.get("items_list") or []:
        if isinstance(row, dict) and row.get("name"):
            name = str(row["name"]).strip()
            if name:
                item_names.append(name)

    vendor_text = " ".join(
        str(v)
        for v in (
            extracted.get("vendor_name"),
            extracted.get("restaurant_name"),
            extracted.get("bill_name"),
            extracted.get("description"),
        )
        if v
    )
    raw_text = str(extracted.get("raw_text") or "")
    combined = f"{vendor_text} {raw_text} {' '.join(item_names)}".strip()

    travel_hit = _classify_travel_receipt(combined)
    if travel_hit:
        return travel_hit

    if item_names:
        items_corpus = " ".join(item_names).lower()
        if _has_food_signals(vendor_text, item_names):
            hit = suggest_categories_from_text(f"{vendor_text} {items_corpus}")
            if hit.get("main_category"):
                return hit

    if vendor_text.strip() or raw_text.strip():
        hit = suggest_categories_from_text(combined)
        if hit.get("main_category"):
            return hit

    return {"main_category": None, "sub_category": None, "line_item": None}


def suggest_categories_from_text(text: str) -> Dict[str, Optional[str]]:
    """Lightweight OCR/chat category hint from merchant/description/line-item text."""
    t = (text or "").lower()

    travel_hit = _classify_travel_receipt(t)
    if travel_hit:
        return travel_hit

    hints = [
        (["google workspace", "microsoft", "saas", "software", "aws", "hosting"], "technology_it", "software_subscriptions", "productivity_tools"),
        (["swiggy", "zomato", "dunzo"], "meals_entertainment", "business_meals", "working_lunches"),
        (["restaurant", "cafe", "dining", "bhagini", "biriyani", "biryani", "tandoori", "kitchen", "dhaba"], "meals_entertainment", "business_meals", "working_lunches"),
        (["lunch", "breakfast", "dinner", "meal", "food"], "meals_entertainment", "business_meals", "working_lunches"),
        (["client entertainment", "client meal", "hospitality"], "meals_entertainment", "business_meals", "client_entertainment"),
        (["petrol", "diesel", "fuel", "hpcl", "iocl", "bharat petroleum"], "travel_transportation", "vehicle_expenses", "fuel_reimbursement"),
        (["rent", "lease", "landlord"], "office_facilities", "rent_lease", "office_rent"),
        (["electric", "internet", "broadband", "wifi", "airtel", "jio", "bsnl"], "office_facilities", "utilities", "electricity"),
        (["legal", "law firm", "attorney"], "professional_legal", "legal", "legal_retainer"),
        (["audit", "accounting", "chartered"], "professional_legal", "accounting_finance", "audit_fees"),
        (["amazon", "flipkart", "myntra"], "miscellaneous", "general", "petty_cash"),
    ]
    for keywords, main, sub, line in hints:
        if any(k in t for k in keywords):
            return {"main_category": main, "sub_category": sub, "line_item": line}
    return {"main_category": None, "sub_category": None, "line_item": None}


def map_business_main_to_legacy_manual(business_main: str) -> str:
    """Picker-friendly value stored as manual_category (business key preferred)."""
    key = (business_main or "").lower().strip()
    if key in BUSINESS_TAXONOMY:
        return key
    reverse = {v: k for k, v in LEGACY_MAIN_TO_BUSINESS.items()}
    return reverse.get(key, key)


# Approver directory for approval tracker UI (L1 → L2 → L3 chain)
APPROVER_DIRECTORY: List[Dict[str, Any]] = [
    {
        "id": 101,
        "role": "manager",
        "name": "Priya S",
        "title": "Manager",
        "department": "Engineering",
        "approval_level": "L1",
    },
    {
        "id": 102,
        "role": "manager",
        "name": "Rahul M",
        "title": "Manager",
        "department": "Sales",
        "approval_level": "L1",
    },
    {
        "id": 201,
        "role": "hod",
        "name": "Arun K",
        "title": "Head of Department",
        "department": "Engineering",
        "approval_level": "L2",
    },
    {
        "id": 202,
        "role": "hod",
        "name": "Meera L",
        "title": "Head of Department",
        "department": "Marketing",
        "approval_level": "L2",
    },
    {
        "id": 301,
        "role": "hr",
        "name": "Sneha P",
        "title": "HR Manager",
        "department": "HR",
        "approval_level": "Support",
    },
    {
        "id": 401,
        "role": "director",
        "name": "Vikram D",
        "title": "Director",
        "department": "Executive",
        "approval_level": "L2",
    },
    {
        "id": 501,
        "role": "finance",
        "name": "Anita R",
        "title": "Finance Lead",
        "department": "Finance",
        "approval_level": "Support",
    },
    {
        "id": 601,
        "role": "admin",
        "name": "Kiran J",
        "title": "Admin",
        "department": "Admin",
        "approval_level": "Support",
    },
    {
        "id": 701,
        "role": "it",
        "name": "Dev IT",
        "title": "IT Lead",
        "department": "IT",
        "approval_level": "Support",
    },
    {
        "id": 801,
        "role": "ceo",
        "name": "Manish Gupta",
        "title": "CEO",
        "department": "Executive",
        "approval_level": "L3",
    },
]
