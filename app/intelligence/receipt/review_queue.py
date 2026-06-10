"""Finance human review queue — future dashboard backing service."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.models import Expense, OCRBill


class ReviewQueueType(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    FRAUD_FLAGGED = "fraud_flagged"
    PENDING_REVIEW = "pending_review"
    ANOMALY = "anomaly"


@dataclass
class ReviewQueueItem:
    expense_id: int
    ocr_bill_id: Optional[int]
    queue_type: ReviewQueueType
    priority: int
    review_status: str
    overall_confidence: Optional[float]
    summary: str
    payload: Dict[str, Any]
    created_at: Optional[datetime]


class ReviewQueueService:
    """
    List receipts needing finance review.

    Phase 1 (current): scan OCRBill.extracted_fields for pending_review.
    Phase 2 (future): dedicated receipt_review_queue_items table + assignee workflow.
    """

    def __init__(self, db: Session):
        self._db = db

    def list_pending(
        self,
        *,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
        queue_type: Optional[ReviewQueueType] = None,
        limit: int = 50,
    ) -> List[ReviewQueueItem]:
        q = (
            self._db.query(OCRBill)
            .options(joinedload(OCRBill.expense))
            .join(Expense, OCRBill.expense_id == Expense.id)
        )
        if user_id is not None:
            q = q.filter(Expense.user_id == user_id)

        rows = q.order_by(OCRBill.processed_at.desc()).limit(500).all()
        items: List[ReviewQueueItem] = []

        for bill in rows:
            fields = bill.extracted_fields or {}
            status = fields.get("review_status")
            if status not in ("pending_review", None) and queue_type != ReviewQueueType.LOW_CONFIDENCE:
                if status != "pending_review":
                    continue

            conf = bill.confidence_score
            item_type = self._classify_item(fields, conf, queue_type)
            if item_type is None:
                continue
            if queue_type and item_type != queue_type:
                continue

            expense = bill.expense
            items.append(
                ReviewQueueItem(
                    expense_id=bill.expense_id,
                    ocr_bill_id=bill.id,
                    queue_type=item_type,
                    priority=self._priority(item_type, conf),
                    review_status=status or "unknown",
                    overall_confidence=conf,
                    summary=self._summary(expense, bill, item_type),
                    payload={
                        "vendor_name": expense.vendor_name if expense else None,
                        "bill_amount": expense.bill_amount if expense else None,
                        "review_token": fields.get("review_token"),
                        "extracted_fields": fields,
                    },
                    created_at=bill.processed_at,
                )
            )
            if len(items) >= limit:
                break

        items.sort(key=lambda x: (-x.priority, x.created_at or datetime.min))
        return items

    def _classify_item(
        self,
        fields: Dict[str, Any],
        confidence: Optional[float],
        filter_type: Optional[ReviewQueueType],
    ) -> Optional[ReviewQueueType]:
        from app.config import settings

        if fields.get("review_status") == "pending_review":
            return ReviewQueueType.PENDING_REVIEW
        threshold = settings.ocr_human_review_threshold
        if confidence is not None and confidence < threshold:
            return ReviewQueueType.LOW_CONFIDENCE
        if fields.get("fraud_flagged"):
            return ReviewQueueType.FRAUD_FLAGGED
        return None

    def _priority(self, queue_type: ReviewQueueType, confidence: Optional[float]) -> int:
        if queue_type == ReviewQueueType.FRAUD_FLAGGED:
            return 100
        if queue_type == ReviewQueueType.PENDING_REVIEW:
            return 80
        if confidence is not None and confidence < 0.4:
            return 60
        return 40

    def _summary(self, expense: Optional[Expense], bill: OCRBill, queue_type: ReviewQueueType) -> str:
        vendor = expense.vendor_name if expense else "Unknown vendor"
        amount = expense.bill_amount if expense else "?"
        return f"{queue_type.value}: {vendor} — ₹{amount} (expense #{bill.expense_id})"
