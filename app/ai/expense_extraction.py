"""Structured expense field extraction — OpenAI for tags/category; regex for facts."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.ai.vendor_guard import sanitize_vendor_name
from app.ai.workflow.entity_extractor import ExpenseEntityExtractor
from app.ai.workflow.slot_parser import infer_food_sub_category, sanitize_sub_category
from app.config import settings

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """Extract structured expense information from the user message.

Rules:
- Return JSON only with keys: merchant, category, subcategory, payment_method, description, tags.
- Do NOT invent amount, date, or merchant if not mentioned.
- payment_method only if the user explicitly stated how they paid (e.g. UPI, cash, card).
- description: optional short phrase using ONLY words from the user message, or null.
- tags: lowercase keyword tags inferred from context (e.g. coffee, cafe, food).
- category: lowercase main category (food, travel, fuel, shopping, groceries, subscriptions, miscellaneous).
- subcategory: lowercase food sub-type when applicable (cafe, restaurant, dining, groceries, swiggy, zomato, office_lunch) or null.
- merchant: normalized merchant name only when clearly mentioned."""

_AI_SUBCATEGORY_ALIASES = {
    "beverages": "cafe",
    "beverage": "cafe",
    "coffee": "cafe",
    "tea": "cafe",
    "restaurants": "restaurant",
    "dining_out": "dining",
    "office lunch": "office_lunch",
}


class ExpenseExtractionResult(BaseModel):
    amount: Optional[float] = None
    vendor: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    payment_method: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    def to_create_arguments(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.amount is not None:
            out["bill_amount"] = self.amount
        if self.vendor:
            out["vendor_name"] = self.vendor
        if self.category:
            out["main_category"] = self.category.strip().lower()
        if self.subcategory:
            out["sub_category"] = self.subcategory.strip().lower()
        if self.payment_method:
            out["payment_method"] = self.payment_method.strip().lower()
        if self.description:
            out["description"] = self.description
        if self.tags:
            out["hashtags"] = self.tags
        return out


def user_description_from_message(text: Optional[str]) -> Optional[str]:
    """Store the user's words — full message or a short phrase from regex, never invented."""
    if not (text or "").strip():
        return None
    stripped = text.strip()
    entities = ExpenseEntityExtractor().extract(stripped)
    short = entities.bill_name
    if short and len(short) <= 80:
        return short
    if len(stripped) <= 500:
        return stripped
    return stripped[:500]


def _normalize_ai_subcategory(raw: Optional[str], main_category: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().lower().replace(" ", "_")
    key = _AI_SUBCATEGORY_ALIASES.get(key, key)
    mapped = sanitize_sub_category(main_category, key)
    return mapped


def _normalize_ai_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().lower().replace(" ", "_")
    aliases = {
        "food_and_drink": "food",
        "food_and_beverage": "food",
        "transport": "travel",
        "transportation": "travel",
    }
    return aliases.get(key, key)


def _merge_tags(*sources: Optional[List[str]]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for src in sources:
        if not src:
            continue
        for tag in src:
            t = str(tag).strip().lower().lstrip("#")
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


class ExpenseExtractionService:
    """Combine regex facts with optional OpenAI enrichment for category/tags."""

    def __init__(self, openai_service: Optional[Any] = None) -> None:
        self._openai = openai_service
        self._regex = ExpenseEntityExtractor()

    def extract_sync(self, user_message: str) -> ExpenseExtractionResult:
        return self._from_regex(user_message)

    async def extract(
        self,
        user_message: str,
        *,
        existing_amount: Optional[float] = None,
    ) -> ExpenseExtractionResult:
        base = self._from_regex(user_message)
        if existing_amount is not None and base.amount is None:
            base.amount = existing_amount

        ai = await self._from_openai(user_message)
        if ai:
            merged = self._merge(base, ai, user_message=user_message)
            logger.info("OPENAI EXPENSE EXTRACTION => %s", merged.model_dump())
            return merged

        logger.info(
            "OPENAI EXPENSE EXTRACTION => %s",
            {"mode": "regex_only", **base.model_dump()},
        )
        return base

    def _from_regex(self, text: str) -> ExpenseExtractionResult:
        if not (text or "").strip():
            return ExpenseExtractionResult()
        entities = self._regex.extract(text)
        sub = None
        main = entities.main_category
        if main == "food":
            sub = infer_food_sub_category(
                vendor_name=entities.vendor_name,
                bill_name=entities.bill_name,
            )
        return ExpenseExtractionResult(
            amount=entities.bill_amount,
            vendor=entities.vendor_name,
            category=main,
            subcategory=sub,
            payment_method=entities.payment_method,
            description=user_description_from_message(text),
            tags=[],
        )

    async def _from_openai(self, text: str) -> Optional[ExpenseExtractionResult]:
        if not settings.openai_api_key or not (text or "").strip():
            logger.info(
                "OPENAI EXPENSE EXTRACTION => %s",
                {"mode": "skipped", "reason": "no_api_key_or_empty_message"},
            )
            return None
        if self._openai is None:
            from app.ai.dependencies import get_openai_service

            self._openai = get_openai_service()
        try:
            raw = await self._openai.extract_json(
                system_prompt=_EXTRACTION_PROMPT,
                user_content=text.strip(),
            )
        except Exception:
            logger.exception("OpenAI expense extraction failed; using regex only")
            return None
        if not raw:
            return None
        merchant = raw.get("merchant") or raw.get("vendor")
        clean_vendor = sanitize_vendor_name(str(merchant).strip()) if merchant else None
        category = _normalize_ai_category(raw.get("category"))
        sub = _normalize_ai_subcategory(raw.get("subcategory"), category)
        pm = raw.get("payment_method")
        if pm:
            pm = str(pm).strip().lower().replace(" ", "_")
        desc = raw.get("description")
        if desc:
            desc = str(desc).strip()
        tags = _merge_tags(raw.get("tags") if isinstance(raw.get("tags"), list) else [])
        return ExpenseExtractionResult(
            vendor=clean_vendor,
            category=category,
            subcategory=sub,
            payment_method=pm if pm else None,
            description=desc,
            tags=tags,
        )

    def _merge(
        self,
        base: ExpenseExtractionResult,
        ai: ExpenseExtractionResult,
        *,
        user_message: str,
    ) -> ExpenseExtractionResult:
        vendor = base.vendor or ai.vendor
        if vendor:
            vendor = sanitize_vendor_name(vendor)
        category = base.category or ai.category
        sub = base.subcategory or ai.subcategory
        if category and sub:
            mapped = sanitize_sub_category(category, sub, vendor_name=vendor, bill_name=base.description)
            sub = mapped or sub
        payment = base.payment_method or ai.payment_method
        description = base.description or user_description_from_message(user_message)
        if ai.description and not base.description:
            if len(ai.description) <= 120:
                description = ai.description
        tags = _merge_tags(base.tags, ai.tags)
        return ExpenseExtractionResult(
            amount=base.amount,
            vendor=vendor,
            category=category,
            subcategory=sub,
            payment_method=payment,
            description=description,
            tags=tags,
        )
