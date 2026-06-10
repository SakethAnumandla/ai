"""Receipt fraud and safety checks."""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.intelligence.receipt.duplicate_similarity import ReceiptDuplicateSimilarityChecker
from app.intelligence.schemas import FraudCheckResult, ReceiptEntities
from app.models import OCRBill


class ReceiptFraudChecker:
    def __init__(self, db: Session):
        self._db = db
        self._similarity = ReceiptDuplicateSimilarityChecker(db)

    def run_all(
        self,
        *,
        user_id: int,
        entities: ReceiptEntities,
        file_hash: Optional[str] = None,
        total_amount: Optional[float] = None,
        exclude_expense_id: Optional[int] = None,
    ) -> List[FraudCheckResult]:
        results: List[FraudCheckResult] = []
        results.append(
            self._similarity.check(
                user_id,
                vendor_name=entities.merchant,
                invoice_id=entities.invoice_id,
                invoice_date=entities.invoice_date,
                total=total_amount or entities.total,
                file_hash=file_hash,
                exclude_expense_id=exclude_expense_id,
            )
        )
        results.append(self._check_future_date(entities))
        results.append(self._check_suspicious_total(total_amount or entities.total))
        results.append(self._check_duplicate_invoice_id(user_id, entities))
        results.append(self._check_total_vs_subtotal(entities))
        return results

    def _check_future_date(self, entities: ReceiptEntities) -> FraudCheckResult:
        if not entities.invoice_date:
            return FraudCheckResult(
                check="future_date",
                passed=True,
                message="Invoice date not extracted.",
            )
        inv = entities.invoice_date
        if inv.tzinfo is None:
            inv = inv.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if inv > now:
            return FraudCheckResult(
                check="future_date",
                passed=False,
                severity="high",
                message="Invoice date is in the future.",
                details={"invoice_date": inv.isoformat()},
            )
        return FraudCheckResult(check="future_date", passed=True, message="Date is valid.")

    def _check_suspicious_total(self, total: Optional[float]) -> FraudCheckResult:
        if total is None:
            return FraudCheckResult(
                check="suspicious_total",
                passed=True,
                message="Total not extracted.",
            )
        if total <= 0:
            return FraudCheckResult(
                check="suspicious_total",
                passed=False,
                severity="medium",
                message="Total amount is zero or negative.",
                details={"total": total},
            )
        if total > 500_000:
            return FraudCheckResult(
                check="suspicious_total",
                passed=False,
                severity="medium",
                message="Unusually high total amount; please verify.",
                details={"total": total},
            )
        return FraudCheckResult(
            check="suspicious_total",
            passed=True,
            message="Total within expected range.",
        )

    def _check_duplicate_invoice_id(
        self, user_id: int, entities: ReceiptEntities
    ) -> FraudCheckResult:
        inv_id = entities.invoice_id
        if not inv_id:
            return FraudCheckResult(
                check="duplicate_invoice_id",
                passed=True,
                message="No invoice ID extracted.",
            )
        dup = (
            self._db.query(OCRBill)
            .filter(
                OCRBill.user_id == user_id,
                OCRBill.bill_number == inv_id,
            )
            .first()
        )
        if dup:
            return FraudCheckResult(
                check="duplicate_invoice_id",
                passed=False,
                severity="high",
                message=f"Invoice ID '{inv_id}' was used on a previous receipt.",
                details={"ocr_bill_id": dup.id, "expense_id": dup.expense_id},
            )
        return FraudCheckResult(
            check="duplicate_invoice_id",
            passed=True,
            message="Invoice ID is unique for this user.",
        )

    def _check_total_vs_subtotal(self, entities: ReceiptEntities) -> FraudCheckResult:
        if entities.subtotal is None or entities.total is None:
            return FraudCheckResult(
                check="amount_consistency",
                passed=True,
                message="Insufficient fields for consistency check.",
            )
        tax = entities.tax or 0.0
        expected = entities.subtotal + tax
        if abs(expected - entities.total) > max(5.0, entities.total * 0.15):
            return FraudCheckResult(
                check="amount_consistency",
                passed=False,
                severity="medium",
                message="Subtotal + tax does not match total; values may be manipulated.",
                details={
                    "subtotal": entities.subtotal,
                    "tax": tax,
                    "total": entities.total,
                    "expected": expected,
                },
            )
        return FraudCheckResult(
            check="amount_consistency",
            passed=True,
            message="Amounts are consistent.",
        )

    @staticmethod
    def has_blocking_failure(checks: List[FraudCheckResult]) -> bool:
        return any(not c.passed and c.severity == "high" for c in checks)
