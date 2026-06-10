"""AI auto-fill — combine OCR entities with user preference memory."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.ai.memory.repository import AIRepository
from app.ai.preferences.service import UserPreferenceService
from app.ai.schemas.common import TenantUserContext
from app.intelligence.receipt.vendor_matcher import VendorMatcher
from app.intelligence.schemas import ReceiptAutofillSuggestion, ReceiptEntities


class ReceiptAutofillService:
    def __init__(self, db: Session):
        self._db = db
        repo = AIRepository(db)
        self._preferences = UserPreferenceService(db, repo)
        self._vendor_matcher = VendorMatcher(db, repo)

    def suggest(
        self,
        ctx: TenantUserContext,
        entities: ReceiptEntities,
        *,
        prefill: dict,
        fields_needing_clarification: List[str],
    ) -> ReceiptAutofillSuggestion:
        display_vendor, norm_vendor, vendor_conf = self._vendor_matcher.match(
            ctx, entities.merchant
        )
        entities.merchant_normalized = norm_vendor

        payment = entities.payment_method
        category = prefill.get("main_category") or entities.main_category
        memory_hints: List[str] = []
        explanation_parts: List[str] = []

        pref_lines = self._preferences.get_preferences_summary(ctx)
        memory_hints.extend(pref_lines[:3])

        if not payment:
            payment = self._preferences.infer_payment_from_history(ctx, ctx.user_id)

        if norm_vendor and vendor_conf >= 0.7:
            vendor_lower = (display_vendor or "").lower()
            if "uber" in vendor_lower:
                explanation_parts.append("Looks like your usual Uber travel expense.")
                if not category:
                    category = "travel"
            elif vendor_conf >= 0.85:
                explanation_parts.append(
                    f"Matched merchant '{display_vendor}' from your expense history."
                )

        if payment and "payment_method" in fields_needing_clarification:
            label = payment.replace("_", " ").upper() if payment == "upi" else payment.replace("_", " ")
            explanation_parts.append(f"Suggested payment: {label} (from your preferences).")

        if category:
            explanation_parts.append(f"Category: {str(category).replace('_', ' ').title()}.")

        return ReceiptAutofillSuggestion(
            bill_name=prefill.get("bill_name"),
            bill_amount=prefill.get("bill_amount") or entities.total,
            vendor_name=display_vendor or entities.merchant,
            main_category=category,
            payment_method=payment,
            explanation=" ".join(explanation_parts) if explanation_parts else None,
            memory_hints=memory_hints,
            fields_needing_clarification=fields_needing_clarification,
        )
