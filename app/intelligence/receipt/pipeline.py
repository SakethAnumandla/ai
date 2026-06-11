"""Receipt intelligence pipeline — OCR → entities → fraud → autofill → human review."""
from sqlalchemy.orm import Session, joinedload

from app.ai.schemas.common import TenantUserContext
from app.ai.conversation.state_machine import normalize_workflow_pending_slots
from app.ai.json_util import json_safe
from app.ai.schemas.memory import DraftExpenseContext
from app.ai.security import resolve_tenant_id
from app.intelligence.receipt.autofill import ReceiptAutofillService
from app.intelligence.receipt.confidence import OCRConfidenceScorer
from app.intelligence.receipt.fraud_checks import ReceiptFraudChecker
from app.intelligence.receipt.human_review import HumanReviewService
from app.intelligence.receipt.json_storage import field_confidence_to_json, merge_extracted_fields
from app.intelligence.receipt.providers import get_default_ocr_provider
from app.intelligence.receipt.providers.base import BaseOCRProvider
from app.intelligence.receipt.pdf_aggregator import PdfReceiptAggregator
from app.intelligence.schemas import ReceiptPipelineResult
from app.models import Expense, User
from app.services.ocr_draft_service import create_ocr_draft


class ReceiptIntelligencePipeline:
    def __init__(self, db: Session, ocr_provider: BaseOCRProvider | None = None):
        self._db = db
        self._ocr = ocr_provider or get_default_ocr_provider()
        self._confidence = OCRConfidenceScorer()
        self._fraud = ReceiptFraudChecker(db)
        self._autofill = ReceiptAutofillService(db)
        self._review = HumanReviewService(db)

    def _normalized_from_bill(self, bill, prefill: dict, ocr_meta: dict | None = None) -> dict:
        meta = ocr_meta or {}
        bill_date = bill.bill_date if bill else prefill.get("bill_date")
        if bill_date is not None and hasattr(bill_date, "isoformat"):
            bill_date = bill_date.isoformat()
        merchant = None
        if bill:
            merchant = bill.vendor_name or bill.restaurant_name
        if not merchant:
            merchant = prefill.get("vendor_name")
        return {
            "merchant": merchant,
            "vendor_gst": bill.vendor_gst if bill else None,
            "invoice_date": bill_date,
            "invoice_id": bill.bill_number if bill else prefill.get("bill_number"),
            "subtotal": bill.subtotal if bill else meta.get("subtotal"),
            "total": (bill.total_amount if bill else None) or prefill.get("bill_amount"),
            "tax": bill.tax_amount if bill else meta.get("tax"),
            "currency": "INR",
            "payment_method": (bill.payment_method if bill else None) or prefill.get("payment_method"),
            "confidence_score": bill.confidence_score if bill else meta.get("confidence_score", 0.5),
        }

    def run_sync(
        self,
        user: User,
        file_info: dict,
        *,
        bill_index: int = 0,
        force_rescan: bool = False,
    ) -> ReceiptPipelineResult:
        tenant_id = resolve_tenant_id(user)
        ctx = TenantUserContext(tenant_id=tenant_id, user_id=user.id)

        ext = file_info.get("file_extension") or "jpg"
        ocr_meta: dict = {}
        if ext.lower() == "pdf":
            pages = self._ocr.extract_pages(
                file_info["file_data"],
                file_info["file_name"],
                ext,
            )
            if len(pages) > 1:
                legacy_pages = [p.get("_legacy") or p for p in pages]
                stitched = PdfReceiptAggregator.stitch(legacy_pages)
                ocr_meta = BaseOCRProvider.normalize(stitched)

        from app.services.ocr_draft_service import create_manual_upload_draft
        from app.utils.ocr_quality import OcrScanUnreadable

        try:
            expense, prefill, is_dup, err = create_ocr_draft(
                self._db,
                user.id,
                file_info,
                batch_id=None,
                bill_index=bill_index,
                force_rescan=force_rescan,
            )
        except OcrScanUnreadable:
            expense, prefill, is_dup = create_manual_upload_draft(
                self._db, user.id, file_info, None, bill_index or 1
            )
            err = None
        if err or not expense:
            expense, prefill, is_dup = create_manual_upload_draft(
                self._db, user.id, file_info, None, bill_index or 1
            )
        if not expense:
            raise RuntimeError("Failed to create expense draft")

        expense = (
            self._db.query(Expense)
            .options(joinedload(Expense.ocr_bills))
            .filter(Expense.id == expense.id)
            .first()
        )
        bill = expense.ocr_bills[0] if expense.ocr_bills else None
        normalized = self._normalized_from_bill(bill, prefill, ocr_meta)

        entities, clarify, ocr_explanations = self._confidence.score_fields(normalized)
        fraud_checks = self._fraud.run_all(
            user_id=user.id,
            entities=entities,
            file_hash=file_info.get("file_hash"),
            total_amount=entities.total or prefill.get("bill_amount"),
            exclude_expense_id=expense.id,
        )
        autofill = self._autofill.suggest(
            ctx, entities, prefill=prefill, fields_needing_clarification=clarify
        )

        overall = (
            sum(fc.confidence for fc in entities.field_confidence.values())
            / max(len(entities.field_confidence), 1)
        )
        blocking = self._fraud.has_blocking_failure(fraud_checks)

        if bill:
            bill.extracted_fields = field_confidence_to_json(entities.field_confidence)
            bill.confidence_score = overall
            if ocr_meta.get("pdf_page_count"):
                bill.extracted_fields = merge_extracted_fields(
                    bill.extracted_fields,
                    {"pdf_page_count": ocr_meta["pdf_page_count"]},
                )
            self._db.commit()

        result = ReceiptPipelineResult(
            expense_id=expense.id,
            ocr_bill_id=bill.id if bill else None,
            entities=entities,
            autofill=autofill,
            fraud_checks=fraud_checks,
            prefill=prefill,
            is_duplicate=is_dup,
            overall_confidence=overall,
            requires_confirmation=True,
            ocr_provider=ocr_meta.get("ocr_provider") or getattr(self._ocr, "name", None),
            pdf_page_count=ocr_meta.get("pdf_page_count"),
            ocr_explanations=ocr_explanations,
            assistant_message="Receipt scanned.",
        )

        result = self._review.evaluate(result, fraud_blocking=blocking)

        if result.requires_human_review and result.review_token:
            self._review.persist_review_state(
                expense.id, result.review_token, result.review_status
            )
            result.review_payload = self._review.build_review_payload(result)

        if not result.requires_human_review:
            msg_parts = []
            if autofill.explanation:
                msg_parts.append(autofill.explanation)
            result.assistant_message = (
                " ".join(msg_parts) if msg_parts else "Receipt scanned. Please review the draft."
            )
        else:
            result.assistant_message = result.assistant_message or (
                "Receipt requires human review before use."
            )

        from app.ai.vendor_guard import looks_like_chat_command, sanitize_vendor_name

        vendor = autofill.vendor_name or entities.merchant
        if vendor:
            clean = sanitize_vendor_name(vendor)
            if clean and (
                not expense.vendor_name or looks_like_chat_command(expense.vendor_name)
            ):
                expense.vendor_name = clean
                self._db.commit()

        return result

    def build_draft_context(self, result: ReceiptPipelineResult) -> DraftExpenseContext:
        if result.requires_human_review:
            af = result.autofill
            vendor = af.vendor_name or result.entities.merchant
            return DraftExpenseContext(
                expense_id=result.expense_id,
                bill_name=af.bill_name,
                bill_amount=af.bill_amount,
                vendor_name=vendor,
                main_category=result.autofill.main_category,
                fields_pending=normalize_workflow_pending_slots(
                    result.autofill.fields_needing_clarification + ["human_review"]
                ),
                raw_ocr_hints={
                    "review_status": result.review_status,
                    "review_token": result.review_token,
                    "review_payload": json_safe(result.review_payload),
                    "entities": result.entities.model_dump(mode="json"),
                    "overall_confidence": result.overall_confidence,
                },
            )

        af = result.autofill
        vendor = af.vendor_name or result.entities.merchant
        return DraftExpenseContext(
            expense_id=result.expense_id,
            bill_name=af.bill_name,
            bill_amount=af.bill_amount,
            vendor_name=vendor,
            main_category=af.main_category,
            fields_pending=normalize_workflow_pending_slots(
                af.fields_needing_clarification
            ),
            raw_ocr_hints={
                "entities": result.entities.model_dump(mode="json"),
                "fraud_checks": [c.model_dump(mode="json") for c in result.fraud_checks],
                "prefill": json_safe(result.prefill),
                "overall_confidence": result.overall_confidence,
            },
        )
