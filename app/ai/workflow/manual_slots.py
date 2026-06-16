"""Manual chat expense slot order, questions, and category pickers (mirrors POST /expenses/manual)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.ai.schemas.chat_ui import CategoryOption, CategoryPickerPayload, ChatUIAction
from app.data.business_taxonomy import (
    BUSINESS_TAXONOMY,
    LEGACY_MAIN_TO_BUSINESS,
    get_manual_categories_payload,
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
    "submitted_by_role": "What is your **role**? (e.g. employee, manager, finance)",
    "bill_date": "What is the **date of the bill**? (e.g. 15/06/2026 or today)",
    "description": "Add a **description** for this expense (or reply **skip**).",
}

ATTACHMENT_QUESTION = (
    "Please attach your bill using **Upload bill** below (JPG, PNG, or PDF). "
    "A receipt is required for manual expenses."
)

_SKIP_RE = re.compile(r"^(skip|none|no|n/a|na|-)$", re.I)
_TODAY_RE = re.compile(r"\b(today|now)\b", re.I)


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
    main_key = LEGACY_MAIN_TO_BUSINESS.get(main, main)
    tree = BUSINESS_TAXONOMY.get(main_key, {})
    return [
        CategoryOption(value=k, label=v.get("label", k))
        for k, v in tree.get("subcategories", {}).items()
    ]


def _line_options(main: str, sub: str) -> List[CategoryOption]:
    main_key = LEGACY_MAIN_TO_BUSINESS.get(main, main)
    tree = BUSINESS_TAXONOMY.get(main_key, {})
    sub_node = tree.get("subcategories", {}).get(sub, {})
    return [
        CategoryOption(
            value=item["value"],
            label=item.get("label", item["value"]),
        )
        for item in sub_node.get("line_items", [])
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


def resolve_main_categories(text: str) -> List[str]:
    """Parse one or more main category values from user text or button payload."""
    raw = (text or "").strip()
    if not raw:
        return []
    parts = re.split(r"[,;|]+", raw)
    payload = get_manual_categories_payload()
    by_value = {c["value"].lower(): c["value"] for c in payload.get("categories", [])}
    by_label = {c["label"].lower(): c["value"] for c in payload.get("categories", [])}
    found: List[str] = []
    for part in parts:
        token = part.strip().lower().replace(" ", "_")
        if not token:
            continue
        if token in by_value:
            found.append(by_value[token])
        elif token in by_label:
            found.append(by_label[token])
        elif token in LEGACY_MAIN_TO_BUSINESS:
            found.append(LEGACY_MAIN_TO_BUSINESS[token])
        elif token in BUSINESS_TAXONOMY:
            found.append(token)
    return list(dict.fromkeys(found))


def resolve_sub_category(text: str, main: str) -> Optional[str]:
    raw = (text or "").strip().lower().replace(" ", "_")
    if not raw:
        return None
    for opt in _sub_options(main):
        if opt.value.lower() == raw or opt.label.lower().replace(" ", "_") == raw:
            return opt.value
    return raw if len(raw) >= 2 else None


def resolve_line_item(text: str, main: str, sub: str) -> Optional[str]:
    raw = (text or "").strip().lower().replace(" ", "_")
    if not raw:
        return None
    for opt in _line_options(main, sub):
        if opt.value.lower() == raw or opt.label.lower().replace(" ", "_") == raw:
            return opt.value
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
        cats = resolve_main_categories(stripped)
        if cats:
            return cats[0], None
        return None, "Please select a category from the list or type a valid category name."

    if slot == "sub_category":
        main = slots.get("main_category")
        if not main:
            return None, "Select a main category first."
        sub = resolve_sub_category(stripped, main)
        if sub:
            return sub, None
        return None, "Please select or type a valid sub-category."

    if slot == "line_item":
        main = slots.get("main_category")
        sub = slots.get("sub_category")
        if not main or not sub:
            return None, "Select category and sub-category first."
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
        if len(stripped) >= 2:
            return stripped[:128], None
        return None, "Please enter your role."

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
    cats = resolve_main_categories(text)
    if not cats:
        return False
    slots["selected_categories"] = cats
    slots["main_category"] = cats[0]
    if len(cats) > 1:
        slots["extra_category_tags"] = cats[1:]
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
