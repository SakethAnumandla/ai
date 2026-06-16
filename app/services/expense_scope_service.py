"""Shared query filters for company + user scoped resources."""
from __future__ import annotations

from sqlalchemy import and_

from app.deps.scope import ExpenseScope
from app.models import Expense, OCRBatch, OCRBill, Wallet


def expense_owner_clause(scope: ExpenseScope):
  return and_(Expense.company_id == scope.company_id, Expense.user_id == scope.user_id)


def expense_owner_for_ctx(ctx, user_id: Optional[int] = None):
  """Filter expenses for AI session context (company + user)."""
  from app.models import Expense

  uid = user_id if user_id is not None else ctx.user_id
  cid = getattr(ctx, "company_id", None) or ctx.tenant_id
  return and_(Expense.user_id == uid, Expense.company_id == cid)


def wallet_owner_clause(scope: ExpenseScope):
  return and_(Wallet.company_id == scope.company_id, Wallet.user_id == scope.user_id)


def ocr_batch_owner_clause(scope: ExpenseScope):
  return and_(OCRBatch.company_id == scope.company_id, OCRBatch.user_id == scope.user_id)


def ocr_bill_owner_clause(scope: ExpenseScope):
  return and_(OCRBill.company_id == scope.company_id, OCRBill.user_id == scope.user_id)
