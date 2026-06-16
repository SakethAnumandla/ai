"""Manual chat expense slot order, questions, and category pickers (mirrors POST /expenses/manual)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.ai.schemas.chat_ui import CategoryOption, CategoryPickerPayload, ChatUIAction
from app.data.business_taxonomy import (
    BUSINESS_TAXONOMY,
    LEGACY_MAIN_TO_BUSINESS,
    OTHERS_LINE_VALUE,
    OTHERS_SUB_VALUE,
    get_manual_categories_payload,
    get_taxonomy_hierarchy,
    normalize_taxonomy_fields,
)

# Same order as manual bill form (logical UX flow)
MANUAL_SLOT_ORDER = [
    "bill_name",
    "bill_amount",
    "vendor_name",
    "main_category",
    "sub_category",
    "line_item",
    "tax_amount",
    "submitted_by_name",
    "submitted_by_role",
    "bill_date",
    "description",
]

MANUAL_SLOT_QUESTIONS = {
    "bill_name": "What is the **bill name**?",
    "bill_amount": "What was the **amount**?",
    "vendor_name": "Which **merchant or vendor** was this with?",
    "main_category": (
        "Select one or more **categories** below (tap to select), or type category names "
        "separated by commas."
    ),
    "sub_category": "Select a **sub-category** below or type its name.",
    "line_item": "Select a **line item** below or type its name.",
    "tax_amount": "What is the **tax amount**? (Enter 0 or reply **skip** if none)",
    "submitted_by_name": "Who is **submitting** this bill? (Your name)",
    "submitted_by_role": (
        "What is your **role**? (e.g. employee, manager, finance — or reply **skip**)"
    ),
    "bill_date": "What is the **date of the bill**? (e.g. 15/06/2026 or today)",
    "description": "Add a **description** for this expense (or reply **skip**).",
}

ATTACHMENT_QUESTION = (
    "You can attach your bill using **Upload bill** below (JPG, PNG, or PDF), "
    "or reply **skip** to continue without a file."
)

_SKIP_RE = re.compile(r"^(skip|none|no|n/a|na|-)$", re.I)
_TODAY_RE = re.compile(r"\b(today|now)\b", re.I)
_CATEGORY_DONE_RE = re.compile(
    r"^(done|continue|next|confirm|ok|okay|proceed|apply|save)$",
    re.I,
)


def _normalize_category_key(value: str) -> str:
    """Normalize labels/values for fuzzy category matching (picker sends labels)."""
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower().strip()).strip("_")


def is_category_done_message(text: str) -> bool:
    return bool(_CATEGORY_DONE_RE.match((text or "").strip()))


def is_others_value(value: Optional[str]) -> bool:
    return (value or "").lower().strip() in (OTHERS_SUB_VALUE, OTHERS_LINE_VALUE, "others")


def others_detail_question(*, step: str) -> str:
    if step == "line_item":
        return "You selected **Others** for the line item. Please type what this expense is for."
    if step == "sub_category":
        return "You selected **Others** for the sub-category. Please type a short description."
    return (
        "You selected **Others**. Please type a short description for this category "
        "(it will be saved on the expense)."
    )


def _category_lookup_maps() -> Tuple[Dict[str, str], Dict[str, str]]:
    payload = get_manual_categories_payload()
    by_value = {c["value"].lower(): c["value"] for c in payload.get("categories", [])}
    by_label: Dict[str, str] = {}
    for c in payload.get("categories", []):
        by_label[_normalize_category_key(c["label"])] = c["value"]
        by_label[c["value"].lower()] = c["value"]
    return by_value, by_label


def _resolve_category_token(token: str, by_value: Dict[str, str], by_label: Dict[str, str]) -> Optional[str]:
    raw = (token or "").strip()
    if not raw or raw == "__more__":
        return None
    lowered = raw.lower().replace(" ", "_")
    if lowered in by_value:
        return by_value[lowered]
    norm = _normalize_category_key(raw)
    if norm in by_label:
        return by_label[norm]
    if lowered in LEGACY_MAIN_TO_BUSINESS:
        return LEGACY_MAIN_TO_BUSINESS[lowered]
    if lowered in BUSINESS_TAXONOMY:
        return lowered
    return None


def _taxonomy_sub_nodes(main: str) -> Dict[str, Any]:
    main_key = LEGACY_MAIN_TO_BUSINESS.get(main, main)
    tree = BUSINESS_TAXONOMY.get(main_key, {})
    subs = tree.get("subcategories", {})
    if subs:
        return subs
    if main_key != OTHERS_SUB_VALUE:
        return {}
    for m in get_taxonomy_hierarchy().get("main_categories", []):
        if m.get("value") == OTHERS_SUB_VALUE:
            return {s["value"]: s for s in m.get("subcategories", [])}
    return {}


def _taxonomy_line_items(main: str, sub: str) -> List[Dict[str, Any]]:
    main_key = LEGACY_MAIN_TO_BUSINESS.get(main, main)
    tree = BUSINESS_TAXONOMY.get(main_key, {})
    sub_node = tree.get("subcategories", {}).get(sub, {})
    items = sub_node.get("line_items", [])
    if items:
        return items
    for m in get_taxonomy_hierarchy().get("main_categories", []):
        if m.get("value") != main_key:
            continue
        for s in m.get("subcategories", []):
            if s.get("value") == sub:
                return s.get("line_items", [])
    return []


def manual_slot_order() -> List[str]:
    return list(MANUAL_SLOT_ORDER)


def slot_question(slot: str) -> str:
    return MANUAL_SLOT_QUESTIONS.get(
        slot,
        f"Could you confirm the {slot.replace('_', ' ')}?",
    )


def _main_options() -> List[CategoryOption]:
    payload = get_manual_categories_payload()
    return [
        CategoryOption(
            value=c["value"],
            label=c["label"],
            icon=c.get("icon"),
        )
        for c in payload.get("categories", [])
    ]


def _sub_options(main: str) -> List[CategoryOption]:
    return [
        CategoryOption(value=k, label=v.get("label", k) if isinstance(v, dict) else k)
        for k, v in _taxonomy_sub_nodes(main).items()
    ]


def _line_options(main: str, sub: str) -> List[CategoryOption]:
    return [
        CategoryOption(
            value=item["value"],
            label=item.get("label", item["value"]),
        )
        for item in _taxonomy_line_items(main, sub)
    ]


def build_category_picker(
    step: str,
    *,
    slots: Dict[str, Any],
) -> Optional[CategoryPickerPayload]:
    main = slots.get("main_category")
    sub = slots.get("sub_category")
    selected = list(slots.get("selected_categories") or [])
    if main and main not in selected:
        selected = [main] + [c for c in selected if c != main]

    if step == "main_category":
        return CategoryPickerPayload(
            step="main",
            multi_select=True,
            main_categories=_main_options(),
            hierarchy=get_manual_categories_payload().get("hierarchy"),
            selected=selected,
        )
    if step == "sub_category" and main:
        return CategoryPickerPayload(
            step="sub",
            multi_select=False,
            parent_main=main,
            options=_sub_options(main),
            selected=[sub] if sub else [],
            hierarchy=get_manual_categories_payload().get("hierarchy"),
        )
    if step == "line_item" and main and sub:
        return CategoryPickerPayload(
            step="line_item",
            multi_select=False,
            parent_main=main,
            parent_sub=sub,
            options=_line_options(main, sub),
            selected=[slots["line_item"]] if slots.get("line_item") else [],
            hierarchy=get_manual_categories_payload().get("hierarchy"),
        )
    return None


def category_ui_actions(step: str, *, slots: Dict[str, Any]) -> List[ChatUIAction]:
    picker = build_category_picker(step, slots=slots)
    if not picker:
        return []
    actions: List[ChatUIAction] = []
    options = picker.main_categories if step == "main_category" else (picker.options or [])
    for opt in options[:12]:
        actions.append(
            ChatUIAction(
                action="select_category",
                label=opt.label,
                fields=[opt.value],
                style="secondary",
            )
        )
    if step == "main_category" and len(options) > 12:
        actions.append(
            ChatUIAction(
                action="select_category",
                label="More categories…",
                fields=["__more__"],
                style="secondary",
            )
        )
    return actions


def resolve_main_categories(
    text: str,
    *,
    existing: Optional[List[str]] = None,
) -> List[str]:
    """Parse one or more main category values from user text or button payload."""
    raw = (text or "").strip()
    if not raw:
        return list(existing or [])

    by_value, by_label = _category_lookup_maps()
    tokens: List[str] = []

    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                tokens = [str(x) for x in parsed if x]
        except (json.JSONDecodeError, TypeError):
            pass

    if not tokens:
        tokens = re.split(r"[,;|]+", raw)

    found: List[str] = list(existing or [])
    for part in tokens:
        resolved = _resolve_category_token(part, by_value, by_label)
        if resolved and resolved not in found:
            found.append(resolved)
    return found


def merge_main_category_selection(slots: Dict[str, Any], text: str) -> bool:
    """Apply multi-category selection; returns True if at least one category resolved."""
    prev = list(slots.get("selected_categories") or [])
    if slots.get("main_category") and slots["main_category"] not in prev:
        prev = [slots["main_category"]] + [c for c in prev if c != slots["main_category"]]
    cats = resolve_main_categories(text, existing=prev if prev else None)
    if not cats and is_category_done_message(text) and prev:
        cats = prev
    if not cats:
        return False
    slots["selected_categories"] = cats
    slots["main_category"] = cats[0]
    if len(cats) > 1:
        slots["extra_category_tags"] = cats[1:]
    else:
        slots.pop("extra_category_tags", None)
    return True


def resolve_sub_category(text: str, main: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None
    norm = _normalize_category_key(raw)
    for opt in _sub_options(main):
        if opt.value.lower() == norm or _normalize_category_key(opt.label) == norm:
            return opt.value
    if is_others_value(raw):
        return OTHERS_SUB_VALUE
    return raw if len(raw) >= 2 else None


def resolve_line_item(text: str, main: str, sub: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None
    norm = _normalize_category_key(raw)
    for opt in _line_options(main, sub):
        if opt.value.lower() == norm or _normalize_category_key(opt.label) == norm:
            return opt.value
    if is_others_value(raw):
        return OTHERS_LINE_VALUE
    return raw if len(raw) >= 2 else None


def try_fill_manual_slot(
    slot: str,
    text: str,
    *,
    slots: Dict[str, Any],
) -> Tuple[Optional[Any], Optional[str]]:
    """Return (value, error_message). value None + error = invalid input."""
    stripped = (text or "").strip()
    if not stripped:
        return None, None

    if slot == "bill_name":
        if len(stripped) >= 2:
            return stripped[:200], None
        return None, "Please enter a bill name (at least 2 characters)."

    if slot == "bill_amount":
        from app.ai.tools.argument_repair import _coerce_float

        val = _coerce_float(stripped)
        if val and val > 0:
            return val, None
        return None, "Please enter a valid amount greater than 0."

    if slot == "vendor_name":
        from app.ai.vendor_guard import looks_like_chat_command

        if looks_like_chat_command(stripped):
            return None, None
        if len(stripped) >= 2 and not stripped.isdigit():
            return stripped[:120], None
        return None, "Please enter a valid vendor or merchant name."

    if slot == "main_category":
        if merge_main_category_selection(slots, stripped):
            return slots["main_category"], None
        return None, "Please select a category from the list or type a valid category name."

    if slot == "sub_category":
        main = slots.get("main_category")
        if not main:
            return None, "Select a main category first."
        if is_category_done_message(stripped) and slots.get("sub_category"):
            return slots["sub_category"], None
        sub = resolve_sub_category(stripped, main)
        if sub:
            return sub, None
        return None, "Please select or type a valid sub-category."

    if slot == "line_item":
        main = slots.get("main_category")
        sub = slots.get("sub_category")
        if not main or not sub:
            return None, "Select category and sub-category first."
        if is_category_done_message(stripped) and slots.get("line_item"):
            return slots["line_item"], None
        li = resolve_line_item(stripped, main, sub)
        if li:
            return li, None
        return None, "Please select or type a valid line item."

    if slot == "tax_amount":
        if _SKIP_RE.match(stripped):
            return 0.0, None
        from app.ai.tools.argument_repair import _coerce_float

        val = _coerce_float(stripped)
        if val is not None and val >= 0:
            return float(val), None
        return None, "Enter a tax amount (number) or reply **skip**."

    if slot == "submitted_by_name":
        if len(stripped) >= 2:
            return stripped[:128], None
        return None, "Please enter the submitter name."

    if slot == "submitted_by_role":
        if _SKIP_RE.match(stripped):
            return None, None
        if len(stripped) >= 2:
            return stripped[:128], None
        return None, "Please enter your role or reply **skip**."

    if slot == "bill_date":
        if _TODAY_RE.match(stripped):
            from datetime import datetime

            return datetime.utcnow().date().isoformat(), None
        try:
            from app.utils.date_parser import parse_bill_date

            return parse_bill_date(stripped).date().isoformat(), None
        except Exception:
            return None, "Please enter a valid date (e.g. 15/06/2026 or **today**)."

    if slot == "description":
        if _SKIP_RE.match(stripped):
            return None, None
        return stripped[:2000], None

    return None, None


def apply_main_category_selection(slots: Dict[str, Any], text: str) -> bool:
    """Apply multi-category selection; returns True if at least one category resolved."""
    return merge_main_category_selection(slots, text)


def apply_others_detail(slots: Dict[str, Any], text: str) -> bool:
    """Persist free-text detail when user picks Others at any taxonomy level."""
    detail = (text or "").strip()
    if len(detail) < 2:
        return False
    slots["others_description"] = detail[:500]
    slots["_others_detail_provided"] = True
    if is_others_value(slots.get("line_item")):
        slots["line_item"] = detail[:120]
    elif is_others_value(slots.get("sub_category")):
        slots["sub_category_raw"] = detail[:120]
        slots["sub_category"] = detail[:120]
    elif is_others_value(slots.get("main_category")):
        slots.setdefault("sub_category", "general")
        slots.setdefault("line_item", OTHERS_LINE_VALUE)
        slots["sub_category_raw"] = detail[:120]
    if not slots.get("description"):
        slots["description"] = detail[:2000]
    return True


def normalize_slots_taxonomy(slots: Dict[str, Any]) -> None:
    taxonomy = normalize_taxonomy_fields(
        slots.get("main_category"),
        slots.get("sub_category"),
        slots.get("line_item"),
    )
    if taxonomy.get("main_category"):
        slots["main_category"] = taxonomy["main_category"]
    if taxonomy.get("sub_category"):
        slots["sub_category"] = taxonomy["sub_category"]
    if taxonomy.get("line_item"):
        slots["line_item"] = taxonomy["line_item"]
