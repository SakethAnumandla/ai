"""Build claim submit HTTP responses."""
from __future__ import annotations

from datetime import datetime as dt
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from app.models import Claim, Expense, ExpenseTax
from app.schemas import (
    ClaimResponse,
    ClaimSubmitResponse,
    ExpenseTaxLineResponse,
    ExpenseTaxSummary,
    PolicyTaxContext,
)
from app.services.tax_service import build_tax_summary
from app.utils.expense_helpers import build_tax_summary_response
from app.utils.policy_tax import policy_tax_context


def build_claim_submit_response(
    db: Session, claim: Claim, meta: dict
) -> ClaimSubmitResponse:
    policy_ctx = policy_tax_context(claim.policy) if claim.policy else None
    tax_summary = None
    expense_id = meta.get("linked_expense_id")
    if expense_id:
        expense = (
            db.query(Expense)
            .options(joinedload(Expense.tax_lines))
            .filter(Expense.id == expense_id)
            .first()
        )
        if expense:
            tax_summary = build_tax_summary_response(expense)
    elif meta.get("tax_payload"):
        tp = meta["tax_payload"]
        lines = tp.get("tax_lines") or []
        if lines:
            pseudo = [
                ExpenseTax(
                    id=i + 1,
                    expense_id=0,
                    country_code=tp.get("country_code", "IN"),
                    tax_regime=tp.get("tax_regime", "india_gst"),
                    tax_type=ln.get("tax_type", "other"),
                    tax_rate=ln.get("tax_rate"),
                    taxable_amount=ln.get("taxable_amount"),
                    cgst=ln.get("cgst") or 0,
                    sgst=ln.get("sgst") or 0,
                    igst=ln.get("igst") or 0,
                    vat=ln.get("vat") or 0,
                    tax_amount=ln.get("tax_amount", 0),
                    recoverable=ln.get("recoverable", True),
                    created_at=dt.utcnow(),
                )
                for i, ln in enumerate(lines)
            ]
            raw = build_tax_summary(pseudo, tp.get("country_code", "IN"))
            tax_summary = ExpenseTaxSummary(
                **{**raw, "lines": [ExpenseTaxLineResponse(**r) for r in raw["lines"]]}
            )

    return ClaimSubmitResponse(
        claim=ClaimResponse.model_validate(claim),
        outcome=meta["outcome"],
        message=meta["message"],
        linked_expense_id=expense_id,
        transaction_type=meta.get("transaction_type"),
        policy_tax_context=PolicyTaxContext(**policy_ctx) if policy_ctx else None,
        tax_summary=tax_summary,
    )
