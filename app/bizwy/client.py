"""Validate Bizwy access tokens and resolve trusted user scope."""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BizwyScope:
  user_id: int
  company_id: int
  currency: Optional[str] = None
  user_type: Optional[str] = None


_CACHE: Dict[str, Tuple[float, BizwyScope]] = {}


def _cache_key(token: str) -> str:
  return hashlib.sha256(token.encode()).hexdigest()


def _strip_bearer(authorization: Optional[str]) -> str:
  if not authorization or not str(authorization).strip():
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="Missing Authorization header",
    )
  raw = str(authorization).strip()
  if raw.lower().startswith("bearer "):
    return raw[7:].strip()
  return raw


def _parse_scope_payload(data: Dict[str, Any]) -> BizwyScope:
  """Accept common Bizwy login / validateToken response shapes."""
  root = data.get("data") if isinstance(data.get("data"), dict) else data
  if not isinstance(root, dict):
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token response")

  user_id = root.get("user_id") or root.get("id")
  company_id = (
    root.get("user_company_id")
    or root.get("company_id")
    or root.get("userCompanyId")
  )
  if user_id is None or company_id is None:
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing user scope")

  currency = (
    root.get("country_currency")
    or root.get("currency")
    or root.get("countryCurrency")
  )
  user_type = root.get("user_type") or root.get("userType")
  return BizwyScope(
    user_id=int(user_id),
    company_id=int(company_id),
    currency=str(currency).strip() if currency else None,
    user_type=str(user_type) if user_type is not None else None,
  )


class BizwyClient:
  def resolve_from_query(
    self,
    *,
    user_id: Optional[int],
    company_id: Optional[int],
    currency: Optional[str] = None,
  ) -> BizwyScope:
    if user_id is None or company_id is None:
      raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="user_id and company_id are required",
      )
    return BizwyScope(
      user_id=int(user_id),
      company_id=int(company_id),
      currency=currency,
    )

  def _get_cached(self, token: str) -> Optional[BizwyScope]:
    entry = _CACHE.get(_cache_key(token))
    if not entry:
      return None
    expires_at, scope = entry
    if time.monotonic() >= expires_at:
      _CACHE.pop(_cache_key(token), None)
      return None
    return scope

  def _set_cached(self, token: str, scope: BizwyScope) -> None:
    ttl = max(30, int(settings.bizwy_token_cache_seconds))
    _CACHE[_cache_key(token)] = (time.monotonic() + ttl, scope)

  def _validate_token_remote(self, token: str) -> BizwyScope:
    cached = self._get_cached(token)
    if cached:
      return cached

    base = (settings.bizwy_api_base_url or "").rstrip("/")
    path = (settings.bizwy_validate_token_path or "").lstrip("/")
    if not base:
      raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Bizwy token validation is not configured",
      )
    url = f"{base}/{path}" if path else base

    try:
      resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.bizwy_http_timeout_seconds,
      )
    except requests.RequestException as exc:
      logger.warning("bizwy.validate_token_failed: %s", exc)
      raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Bizwy identity service unavailable",
      ) from exc

    if resp.status_code == 401:
      raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if resp.status_code >= 400:
      logger.warning(
        "bizwy.validate_token_http_error status=%s body=%s",
        resp.status_code,
        resp.text[:300],
      )
      raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token validation failed",
      )

    try:
      payload = resp.json()
    except ValueError as exc:
      raise HTTPException(
        status.HTTP_502_BAD_GATEWAY, "Invalid Bizwy token response"
      ) from exc

    if payload.get("success") is False or payload.get("status") == "error":
      raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    scope = _parse_scope_payload(payload)
    self._set_cached(token, scope)
    return scope

  def validate_token(self, authorization: str) -> BizwyScope:
    token = _strip_bearer(authorization)
    return self._validate_token_remote(token)

  def _query_scope_available(
    self,
    *,
    user_id: Optional[int],
    company_id: Optional[int],
  ) -> bool:
    return user_id is not None and company_id is not None

  def _assert_scope_matches_query(
    self,
    scope: BizwyScope,
    *,
    user_id: Optional[int],
    company_id: Optional[int],
  ) -> None:
    if user_id is not None and int(user_id) != scope.user_id:
      raise HTTPException(status.HTTP_403_FORBIDDEN, "user_id mismatch")
    if company_id is not None and int(company_id) != scope.company_id:
      raise HTTPException(status.HTTP_403_FORBIDDEN, "company_id mismatch")

  def _resolve_from_query_with_mode(
    self,
    *,
    user_id: Optional[int],
    company_id: Optional[int],
    currency: Optional[str],
    mode: str,
  ) -> BizwyScope:
    if not self._query_scope_available(user_id=user_id, company_id=company_id):
      if mode in {"dev", "hybrid"}:
        raise HTTPException(
          status_code=status.HTTP_400_BAD_REQUEST,
          detail="user_id and company_id are required",
        )
      raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing Authorization header",
      )
    logger.info(
      "bizwy.resolve_user query_scope mode=%s user_id=%s company_id=%s",
      mode,
      user_id,
      company_id,
    )
    return self.resolve_from_query(
      user_id=user_id, company_id=company_id, currency=currency
    )

  def resolve_user(
    self,
    authorization: Optional[str],
    *,
    user_id: Optional[int] = None,
    company_id: Optional[int] = None,
    currency: Optional[str] = None,
  ) -> BizwyScope:
    mode = (settings.bizwy_auth_mode or "hybrid").strip().lower()
    if mode == "dev":
      return self.resolve_from_query(
        user_id=user_id, company_id=company_id, currency=currency
      )

    has_auth = bool(authorization and str(authorization).strip())
    has_query = self._query_scope_available(user_id=user_id, company_id=company_id)
    allow_query_fallback = bool(settings.bizwy_token_query_fallback)

    if not has_auth:
      if mode == "hybrid" or (mode == "token" and allow_query_fallback):
        return self._resolve_from_query_with_mode(
          user_id=user_id,
          company_id=company_id,
          currency=currency,
          mode=mode,
        )
      raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing Authorization header",
      )

    try:
      scope = self.validate_token(authorization)
    except HTTPException as exc:
      can_fallback = (
        allow_query_fallback
        and has_query
        and mode in {"hybrid", "token"}
        and exc.status_code in {
          status.HTTP_401_UNAUTHORIZED,
          status.HTTP_502_BAD_GATEWAY,
          status.HTTP_503_SERVICE_UNAVAILABLE,
        }
      )
      if can_fallback:
        logger.warning(
          "bizwy.resolve_user token_validation_failed status=%s; using query scope",
          exc.status_code,
        )
        return self._resolve_from_query_with_mode(
          user_id=user_id,
          company_id=company_id,
          currency=currency,
          mode=mode,
        )
      raise

    self._assert_scope_matches_query(
      scope, user_id=user_id, company_id=company_id
    )
    return scope


bizwy_client = BizwyClient()
