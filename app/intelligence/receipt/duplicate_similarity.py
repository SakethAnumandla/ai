"""Semantic-ish duplicate detection — same invoice, different photo/hash."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.intelligence.receipt.vendor_matcher import normalize_vendor
from app.intelligence.schemas import FraudCheckResult
from app.models import Expense, OCRBill


class ReceiptDuplicateSimilarityChecker:
    """
    Detect likely duplicate receipts when file hash differs
    (e.g. same invoice photographed twice).
    """

    def __init__(
        self,
        db: Session,
        *,
        amount_tolerance_pct: float = 0.02,
        date_tolerance_days: int = 2,
        similarity_threshold: float = 0.82,
    ):
        self._db = db
        self._amount_tol = amount_tolerance_pct
        self._date_tol = date_tolerance_days
        self._threshold = similarity_threshold

    def find_similar(
        self,
        user_id: int,
        *,
        vendor_name: Optional[str],
        invoice_id: Optional[str],
        invoice_date: Optional[datetime],
        total: Optional[float],
        exclude_expense_id: Optional[int] = None,
    ) -> Tuple[Optional[Expense], float]:
        candidates = (
            self._db.query(Expense)
            .filter(Expense.user_id == user_id)
            .order_by(Expense.created_at.desc())
            .limit(200)
            .all()
        )
        best_score = 0.0
        best: Optional[Expense] = None
        norm_vendor = normalize_vendor(vendor_name)

        for exp in candidates:
            if exclude_expense_id and exp.id == exclude_expense_id:
                continue
            score = self._similarity_score(
                norm_vendor=norm_vendor,
                invoice_id=invoice_id,
                invoice_date=invoice_date,
                total=total,
                candidate=exp,
            )
            if score > best_score:
                best_score = score
                best = exp

        if best_score >= self._threshold:
            return best, best_score
        return None, best_score

    def _similarity_score(
        self,
        *,
        norm_vendor: Optional[str],
        invoice_id: Optional[str],
        invoice_date: Optional[datetime],
        total: Optional[float],
        candidate: Expense,
    ) -> float:
        score = 0.0
        weights = 0.0

        if invoice_id and candidate.bill_number:
            weights += 0.4
            if str(invoice_id).strip().lower() == str(candidate.bill_number).strip().lower():
                score += 0.4

        if total and candidate.bill_amount:
            weights += 0.35
            diff = abs(float(total) - float(candidate.bill_amount))
            tol = max(1.0, float(total) * self._amount_tol)
            if diff <= tol:
                score += 0.35

        if norm_vendor and candidate.vendor_name:
            weights += 0.15
            cv = normalize_vendor(candidate.vendor_name)
            if cv == norm_vendor:
                score += 0.15
            elif cv and norm_vendor and (cv in norm_vendor or norm_vendor in cv):
                score += 0.08

        if invoice_date and candidate.bill_date:
            weights += 0.1
            d1 = invoice_date.replace(tzinfo=None) if invoice_date.tzinfo else invoice_date
            d2 = candidate.bill_date.replace(tzinfo=None) if candidate.bill_date.tzinfo else candidate.bill_date
            if abs((d1 - d2).days) <= self._date_tol:
                score += 0.1

        if weights == 0:
            return 0.0
        return score / weights if weights < 1.0 else score

    def check(
        self,
        user_id: int,
        *,
        vendor_name: Optional[str],
        invoice_id: Optional[str],
        invoice_date: Optional[datetime],
        total: Optional[float],
        file_hash: Optional[str],
        exclude_expense_id: Optional[int] = None,
    ) -> FraudCheckResult:
        from app.utils.dedup import find_expense_by_file_hash

        if file_hash:
            existing = find_expense_by_file_hash(self._db, user_id, file_hash)
            if existing:
                return FraudCheckResult(
                    check="duplicate_receipt",
                    passed=False,
                    severity="high",
                    message=f"Exact duplicate file (expense #{existing.id}).",
                    details={"expense_id": existing.id, "match": "hash"},
                )

        similar, sim_score = self.find_similar(
            user_id,
            vendor_name=vendor_name,
            invoice_id=invoice_id,
            invoice_date=invoice_date,
            total=total,
            exclude_expense_id=exclude_expense_id,
        )
        if similar:
            return FraudCheckResult(
                check="semantic_duplicate",
                passed=False,
                severity="high",
                message=(
                    f"This receipt appears similar to expense #{similar.id} "
                    f"({similar.bill_name}, ₹{similar.bill_amount:,.2f}) — possibly the same invoice re-photographed."
                ),
                details={
                    "expense_id": similar.id,
                    "similarity_score": round(sim_score, 3),
                    "match": "semantic",
                },
            )
        return FraudCheckResult(
            check="semantic_duplicate",
            passed=True,
            message="No semantically similar receipt found.",
            details={"best_similarity_score": round(sim_score, 3)},
        )
