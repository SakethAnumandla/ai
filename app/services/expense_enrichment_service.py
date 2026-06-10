"""
Single source of truth for expense field enrichment (vendor, category, tags, etc.).

Used by: chatbot tools, OCR drafts, voice, and any path that builds ExpenseCreate payloads.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.ai.expense_extraction import (
    ExpenseExtractionResult,
    ExpenseExtractionService,
    user_description_from_message,
)
from app.ai.vendor_guard import sanitize_vendor_name
from app.ai.workflow.entity_extractor import ExpenseEntityExtractor
from app.ai.workflow.slot_parser import infer_food_sub_category, sanitize_sub_category
from app.models import MainCategory, TransactionType
from app.utils.category_hashtags import default_expense_hashtags, normalize_hashtags_list
from app.utils.ocr_categories import resolve_classification
from app.utils.expense_helpers import parse_payment_method

logger = logging.getLogger(__name__)

# LLM / API aliases → tool & ExpenseCreate field names
_FIELD_ALIASES = (
    ("merchant", "vendor_name"),
    ("merchant_name", "vendor_name"),
    ("vendor", "vendor_name"),
    ("title", "bill_name"),
    ("amount", "bill_amount"),
    ("category", "main_category"),
    ("subcategory", "sub_category"),
    ("tags", "hashtags"),
)


def apply_field_aliases(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Map common external names onto canonical expense fields."""
    out = dict(arguments or {})
    for alias, target in _FIELD_ALIASES:
        if alias in out and out.get(alias) not in (None, "", []) and not out.get(target):
            out[target] = out.pop(alias)
        elif alias in out:
            out.pop(alias, None)
    return out


class ExpenseEnrichmentService:
    """NL + OCR enrichment for expense rows."""

    def __init__(self, openai_service: Optional[Any] = None) -> None:
        self._extractor = ExpenseExtractionService(openai_service=openai_service)

    def extract_sync(self, description: str) -> ExpenseExtractionResult:
        return self._extractor.extract_sync(description)

    async def enrich_from_text(
        self,
        description: str,
        *,
        existing_amount: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Extract structured fields from a user message or OCR description text."""
        if not (description or "").strip():
            return {}
        result = await self._extractor.extract(
            description.strip(),
            existing_amount=existing_amount,
        )
        payload = result.to_create_arguments()
        logger.info("EXTRACTED_ENTITIES=%s", result.model_dump())
        logger.info("EXPENSE_PAYLOAD=%s", payload)
        return payload

    def enrich_from_ocr(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """Map OCR pipeline output to ExpenseCreate / tool argument fields."""
        if not extracted:
            return {}
        transaction_type, main_category, sub_category = resolve_classification(
            extracted, extracted.get("raw_text")
        )
        vendor = extracted.get("vendor_name") or extracted.get("restaurant_name")
        vendor = sanitize_vendor_name(vendor) if vendor else None
        main_val = (
            main_category.value
            if isinstance(main_category, MainCategory)
            else str(main_category or "miscellaneous").lower()
        )
        pm = extracted.get("payment_method")
        if pm:
            pm = (
                pm.value
                if hasattr(pm, "value")
                else str(pm).strip().lower().replace(" ", "_")
            )
        tags = normalize_hashtags_list(
            default_expense_hashtags(
                main_val,
                sub_category,
                vendor_name=vendor,
                bill_name=extracted.get("bill_name"),
            )
        )
        payload: Dict[str, Any] = {
            "bill_amount": extracted.get("total_amount"),
            "vendor_name": vendor,
            "main_category": main_val,
            "sub_category": sub_category,
            "payment_method": pm,
            "description": extracted.get("description"),
            "bill_number": extracted.get("bill_number"),
            "bill_date": extracted.get("bill_date"),
            "hashtags": tags,
            "transaction_type": TransactionType.EXPENSE,
        }
        logger.info("EXTRACTED_ENTITIES=%s", {"source": "ocr", "vendor": vendor, "category": main_val})
        logger.info("EXPENSE_PAYLOAD=%s", payload)
        return {k: v for k, v in payload.items() if v not in (None, "", [])}

    async def enrich_tool_arguments(
        self,
        arguments: Dict[str, Any],
        *,
        user_message: Optional[str] = None,
        source_utterance: Optional[str] = None,
        workflow_slots: Optional[Dict[str, Any]] = None,
        extracted: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Merge aliases, NL extraction, and workflow slots onto expense.create.v1 args."""
        from app.ai.tools.expense_create_enrichment import enrich_expense_create_arguments

        out = apply_field_aliases(arguments)
        return enrich_expense_create_arguments(
            out,
            user_message=user_message,
            source_utterance=source_utterance,
            workflow_slots=workflow_slots,
            extracted=extracted,
        )

    def build_expense_create_payload(
        self,
        *,
        bill_name: str,
        bill_amount: float,
        bill_date,
        main_category: MainCategory,
        sub_category: Optional[str] = None,
        vendor_name: Optional[str] = None,
        payment_method: Optional[str] = None,
        description: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
        transaction_type: TransactionType = TransactionType.EXPENSE,
    ) -> Dict[str, Any]:
        """Canonical dict for ExpenseCreate construction."""
        tags = normalize_hashtags_list(hashtags or [])
        if not tags:
            tags = default_expense_hashtags(
                main_category.value,
                sub_category,
                vendor_name=vendor_name,
                bill_name=bill_name,
            )
        payload = {
            "bill_name": bill_name,
            "bill_amount": float(bill_amount),
            "bill_date": bill_date,
            "transaction_type": transaction_type,
            "main_category": main_category,
            "sub_category": sub_category,
            "vendor_name": sanitize_vendor_name(vendor_name),
            "payment_method": payment_method,
            "description": (description or "").strip() or None,
            "hashtags": tags or None,
        }
        logger.info("EXPENSE_PAYLOAD=%s", payload)
        return payload
