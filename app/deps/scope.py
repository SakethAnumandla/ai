"""Multi-tenant scope dependencies for expense APIs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Query, status

from app.bizwy.client import BizwyScope, bizwy_client


@dataclass(frozen=True)
class ScopedActor:
  """User-like adapter for services that expect `.id` during scope migration."""

  user_id: int
  company_id: int
  currency: Optional[str] = None

  @classmethod
  def from_scope(cls, scope: ExpenseScope) -> "ScopedActor":
    return cls(
      user_id=scope.user_id,
      company_id=scope.company_id,
      currency=scope.currency,
    )

  @property
  def id(self) -> int:
    return self.user_id


@dataclass(frozen=True)
class ExpenseScope:
  """Trusted owner scope for user-scoped resources (expenses, wallet, drafts)."""

  user_id: int
  company_id: int
  currency: Optional[str] = None
  user_type: Optional[str] = None

  @property
  def id(self) -> int:
    return self.user_id

  @classmethod
  def from_bizwy(cls, scope: BizwyScope) -> "ExpenseScope":
    return cls(
      user_id=scope.user_id,
      company_id=scope.company_id,
      currency=scope.currency,
      user_type=scope.user_type,
    )


@dataclass(frozen=True)
class CompanyScope:
  """Company-wide scope for approvals and shared company resources."""

  company_id: int
  approver_user_id: int
  currency: Optional[str] = None
  user_type: Optional[str] = None

  @classmethod
  def from_bizwy(cls, scope: BizwyScope) -> "CompanyScope":
    return cls(
      company_id=scope.company_id,
      approver_user_id=scope.user_id,
      currency=scope.currency,
      user_type=scope.user_type,
    )


def _resolve_authorization(
  authorization: Optional[str],
  access_token: Optional[str],
) -> Optional[str]:
  if authorization and str(authorization).strip():
    return authorization
  if access_token and str(access_token).strip():
    token = str(access_token).strip()
    if token.lower().startswith("bearer "):
      return token
    return f"Bearer {token}"
  return None


async def get_expense_scope(
  authorization: Optional[str] = Header(None, alias="Authorization"),
  access_token: Optional[str] = Query(None),
  user_id: int = Query(..., ge=1, description="Bizwy user id (required)"),
  company_id: int = Query(..., ge=1, description="Bizwy company id (required)"),
  user_type: Optional[str] = Query(None, description="Optional Bizwy role hint (e.g. finance_admin)"),
  country_currency: Optional[str] = Query(None, alias="country_currency"),
) -> ExpenseScope:
  scope = bizwy_client.resolve_user(
    _resolve_authorization(authorization, access_token),
    user_id=user_id,
    company_id=company_id,
    currency=country_currency,
    user_type=user_type,
  )
  return ExpenseScope.from_bizwy(scope)


async def get_company_scope(
  authorization: Optional[str] = Header(None, alias="Authorization"),
  access_token: Optional[str] = Query(None),
  user_id: int = Query(..., ge=1, description="Bizwy user id (required)"),
  company_id: int = Query(..., ge=1, description="Bizwy company id (required)"),
  user_type: Optional[str] = Query(None, description="Optional Bizwy role hint (e.g. finance_admin)"),
  country_currency: Optional[str] = Query(None, alias="country_currency"),
) -> CompanyScope:
  scope = bizwy_client.resolve_user(
    _resolve_authorization(authorization, access_token),
    user_id=user_id,
    company_id=company_id,
    currency=country_currency,
    user_type=user_type,
  )
  return CompanyScope.from_bizwy(scope)


def assert_expense_owner(expense, scope: ExpenseScope) -> None:
  if (
    getattr(expense, "company_id", None) != scope.company_id
    or expense.user_id != scope.user_id
  ):
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
