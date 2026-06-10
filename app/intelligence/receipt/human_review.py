"""Human review flow for low-confidence OCR — no silent auto-draft."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.json_util import json_safe
from app.config import settings
from app.intelligence.schemas import ReceiptPipelineResult
from app.models import Expense, ExpenseStatus, OCRBill


class HumanReviewService:
    def __init__(self, db: Session):
        self._db = db

    def evaluate(
        self,
        result: ReceiptPipelineResult,
        *,
        fraud_blocking: bool,
    ) -> ReceiptPipelineResult:
        """Set human_review flags when OCR should not proceed silently."""
        low_conf = result.overall_confidence < settings.ocr_human_review_threshold
        clarify = bool(result.autofill.fields_needing_clarification)
        failed_fraud = any(not c.passed for c in result.fraud_checks)

        needs_review = (
            low_conf
            or clarify
            or failed_fraud
            or fraud_blocking
            or result.is_duplicate
        )
        result.requires_human_review = needs_review
        result.requires_confirmation = needs_review or result.requires_confirmation

        if needs_review:
            result.review_token = secrets.token_urlsafe(32)
            result.review_status = "pending_review"
            result.assistant_message = self._build_review_message(result)
        else:
            result.review_status = "auto_approved"
        return result

    def _build_review_message(self, result: ReceiptPipelineResult) -> str:
        parts = [
            "This receipt needs your review before it can be used.",
        ]
        if result.autofill.fields_needing_clarification:
            fields = ", ".join(
                f.replace("_", " ") for f in result.autofill.fields_needing_clarification
            )
            parts.append(f"Please confirm: {fields}.")
        if result.overall_confidence < settings.ocr_human_review_threshold:
            parts.append(
                f"OCR confidence is {result.overall_confidence:.0%}; verify amounts and merchant."
            )
        for c in result.fraud_checks:
            if not c.passed:
                parts.append(c.message)
        parts.append("Use the review screen to confirm or correct the extracted fields.")
        return " ".join(parts)

    def build_review_payload(self, result: ReceiptPipelineResult) -> Dict[str, Any]:
        return {
            "review_token": result.review_token,
            "review_status": result.review_status,
            "expense_id": result.expense_id,
            "ocr_bill_id": result.ocr_bill_id,
            "overall_confidence": result.overall_confidence,
            "entities": result.entities.model_dump(mode="json"),
            "autofill": result.autofill.model_dump(),
            "prefill": result.prefill,
            "fraud_checks": [c.model_dump() for c in result.fraud_checks],
            "fields_for_review": result.autofill.fields_needing_clarification,
            "ocr_explanations": result.ocr_explanations,
            "field_confidence_reasons": {
                k: v.confidence_reason
                for k, v in result.entities.field_confidence.items()
                if v.confidence_reason
            },
        }

    def persist_review_state(self, expense_id: int, review_token: str, status: str) -> None:
        bill = (
            self._db.query(OCRBill)
            .filter(OCRBill.expense_id == expense_id)
            .first()
        )
        if bill:
            fields = dict(bill.extracted_fields or {})
            fields["review_status"] = status
            fields["review_token"] = review_token
            bill.extracted_fields = json_safe(fields)
            self._db.commit()

    def confirm_review(
        self,
        *,
        user_id: int,
        expense_id: int,
        review_token: str,
        corrections: Optional[Dict[str, Any]] = None,
    ) -> Expense:
        expense = (
            self._db.query(Expense)
            .filter(Expense.id == expense_id, Expense.user_id == user_id)
            .first()
        )
        if not expense:
            raise ValueError("Expense not found")

        bill = (
            self._db.query(OCRBill)
            .filter(OCRBill.expense_id == expense_id)
            .first()
        )
        if bill:
            stored = (bill.extracted_fields or {}).get("review_token")
            if stored and stored != review_token:
                raise ValueError("Invalid review token")
            fields = dict(bill.extracted_fields or {})
            fields["review_status"] = "confirmed"
            bill.extracted_fields = json_safe(fields)

        if corrections:
            if "bill_amount" in corrections:
                expense.bill_amount = float(corrections["bill_amount"])
            if "vendor_name" in corrections:
                expense.vendor_name = corrections["vendor_name"]
            if "bill_name" in corrections:
                expense.bill_name = corrections["bill_name"]

        if expense.status != ExpenseStatus.DRAFT:
            expense.status = ExpenseStatus.DRAFT

        self._db.commit()
        self._db.refresh(expense)
        return expense
