"""Map extracted entities and workflow slots onto expense.create.v1 arguments."""
import logging
from typing import Any, Dict, Optional

from app.ai.expense_extraction import (
    ExpenseExtractionService,
    user_description_from_message,
)
from app.ai.vendor_guard import looks_like_chat_command, sanitize_vendor_name
from app.ai.workflow.entity_extractor import ExpenseEntityExtractor
from app.ai.workflow.slot_parser import infer_food_sub_category, sanitize_sub_category

logger = logging.getLogger(__name__)

_BAD_TITLE_MARKERS = (
    "bill was",
    "add it",
    "add to",
    "and the bill",
    "help me",
    "log it",
    "record it",
    "expenses",
)

_SHORT_ACKS = frozenset(
    {"yes", "yeah", "yep", "ok", "okay", "confirm", "confirmed", "sure", "proceed", "go ahead"}
)


def bill_name_needs_repair(bill_name: Optional[str]) -> bool:
    if not bill_name or not str(bill_name).strip():
        return True
    text = str(bill_name).strip()
    if looks_like_chat_command(text):
        return True
    lowered = text.lower()
    if any(marker in lowered for marker in _BAD_TITLE_MARKERS):
        return True
    if len(text.split()) > 6:
        return True
    return False


def _resolve_source_message(
    *,
    user_message: Optional[str],
    source_utterance: Optional[str],
    workflow_slots: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Prefer the original expense sentence over a follow-up like 'yes'."""
    if source_utterance and len(source_utterance.strip()) > 12:
        return source_utterance.strip()
    if user_message and len(user_message.strip()) > 12:
        lowered = user_message.strip().lower()
        if lowered not in _SHORT_ACKS:
            return user_message.strip()
    if workflow_slots and workflow_slots.get("description"):
        desc = str(workflow_slots["description"]).strip()
        if len(desc) > 12:
            return desc
    return user_message


def _pick_bill_name(
    *,
    current: Optional[str],
    vendor_name: Optional[str],
    workflow_slots: Optional[Dict[str, Any]],
    short_title: Optional[str] = None,
) -> str:
    if workflow_slots:
        slot_title = workflow_slots.get("bill_name")
        if slot_title and not bill_name_needs_repair(slot_title):
            return str(slot_title).strip()

    if short_title and not bill_name_needs_repair(short_title):
        return str(short_title).strip()

    if current and not bill_name_needs_repair(current):
        return str(current).strip()

    if vendor_name:
        return vendor_name

    return "expense"


def _apply_aliases(out: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.expense_enrichment_service import apply_field_aliases

    return apply_field_aliases(out)


def _merge_extraction_into(
    out: Dict[str, Any],
    extracted_prefill: Dict[str, Any],
    *,
    user_message: Optional[str],
) -> Dict[str, Any]:
    for key in (
        "bill_amount",
        "vendor_name",
        "payment_method",
        "main_category",
        "sub_category",
        "description",
        "hashtags",
    ):
        if out.get(key) in (None, "", []):
            val = extracted_prefill.get(key)
            if val not in (None, "", []):
                out[key] = val

    if not out.get("description") and user_message:
        out["description"] = user_description_from_message(user_message)
    return out


def enrich_expense_create_arguments(
    arguments: Dict[str, Any],
    *,
    user_message: Optional[str] = None,
    source_utterance: Optional[str] = None,
    workflow_slots: Optional[Dict[str, Any]] = None,
    extracted: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Apply entity extraction and workflow memory so merchant → vendor_name.
    Description stays separate from bill_name (user-originated text).
    """
    out = _apply_aliases(dict(arguments or {}))
    logger.info("expense.create enrich input=%s", out)
    slots = workflow_slots or {}
    source_text = _resolve_source_message(
        user_message=user_message,
        source_utterance=source_utterance,
        workflow_slots=slots,
    )

    extracted_prefill = extracted
    if extracted_prefill is None and source_text:
        sync = ExpenseExtractionService().extract_sync(source_text)
        logger.info("EXTRACTED EXPENSE=%s", sync.model_dump())
        extracted_prefill = sync.to_create_arguments()

    if extracted_prefill:
        out = _merge_extraction_into(out, extracted_prefill, user_message=source_text)

    for key in (
        "bill_amount",
        "vendor_name",
        "payment_method",
        "main_category",
        "sub_category",
        "description",
        "hashtags",
    ):
        if out.get(key) in (None, "", []):
            if slots.get(key) not in (None, "", []):
                out[key] = slots[key]

    clean_vendor = sanitize_vendor_name(out.get("vendor_name"))
    if not clean_vendor:
        clean_vendor = sanitize_vendor_name(slots.get("vendor_name"))
    if clean_vendor:
        out["vendor_name"] = clean_vendor
    else:
        out.pop("vendor_name", None)

    short_title = ExpenseEntityExtractor().extract(source_text).bill_name if source_text else None

    out["bill_name"] = _pick_bill_name(
        current=out.get("bill_name"),
        vendor_name=out.get("vendor_name"),
        workflow_slots=slots,
        short_title=short_title,
    )

    main = (out.get("main_category") or "").strip().lower()
    if main == "food" and not out.get("sub_category"):
        inferred = infer_food_sub_category(
            vendor_name=out.get("vendor_name"),
            bill_name=out.get("bill_name"),
        )
        if inferred:
            out["sub_category"] = inferred

    if out.get("sub_category"):
        mapped = sanitize_sub_category(
            out.get("main_category"),
            out["sub_category"],
            vendor_name=out.get("vendor_name"),
            bill_name=out.get("bill_name"),
        )
        if mapped:
            out["sub_category"] = mapped
        elif main == "food":
            out.pop("sub_category", None)

    if out.get("payment_method") in (None, "", []) and slots.get("payment_method"):
        out["payment_method"] = slots["payment_method"]

    logger.info("FINAL EXPENSE PAYLOAD => %s", out)
    return out


async def enrich_expense_create_arguments_async(
    arguments: Dict[str, Any],
    *,
    user_message: Optional[str] = None,
    source_utterance: Optional[str] = None,
    workflow_slots: Optional[Dict[str, Any]] = None,
    openai_service: Optional[Any] = None,
) -> Dict[str, Any]:
    """Async enrichment with OpenAI tags/category when configured."""
    existing_amount = arguments.get("bill_amount") if arguments else None
    slots = workflow_slots or {}
    source_text = _resolve_source_message(
        user_message=user_message,
        source_utterance=source_utterance,
        workflow_slots=slots,
    )
    extracted_dict: Optional[Dict[str, Any]] = None
    if source_text:
        svc = ExpenseExtractionService(openai_service=openai_service)
        result = await svc.extract(
            source_text,
            existing_amount=float(existing_amount) if existing_amount else None,
        )
        extracted_dict = result.to_create_arguments()
    return enrich_expense_create_arguments(
        arguments,
        user_message=user_message,
        source_utterance=source_utterance,
        workflow_slots=workflow_slots,
        extracted=extracted_dict,
    )

