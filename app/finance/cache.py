"""Redis-backed analytics result cache (sync)."""
import hashlib
import json
import logging
from typing import Any, Callable, Dict, Optional, TypeVar

import redis

from app.config import settings
from app.finance.scope import is_company_scope
from app.models import User

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AnalyticsCache:
    """
    Cache expensive finance analytics (quarterly trends, vendors, departments).
    Falls through to compute on miss or Redis unavailable.
    """

    PREFIX = "finance:analytics:"

    def __init__(self, redis_url: Optional[str] = None):
        self._url = redis_url or settings.redis_url
        self._client: Optional[redis.Redis] = None
        self._enabled = settings.analytics_cache_enabled

    def _get_client(self) -> Optional[redis.Redis]:
        if not self._enabled or not settings.redis_enabled:
            return None
        if self._client is None:
            try:
                self._client = redis.from_url(
                    self._url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                self._client.ping()
            except Exception as exc:
                logger.warning("Analytics cache Redis unavailable: %s", exc)
                self._client = None
        return self._client

    def build_key(
        self,
        report: str,
        *,
        tenant_id: int,
        user: User,
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        scope = "company" if is_company_scope(user) else (
            f"dept:{user.department.value}" if user.department else f"user:{user.id}"
        )
        param_blob = json.dumps(params or {}, sort_keys=True, default=str)
        digest = hashlib.sha256(param_blob.encode()).hexdigest()[:16]
        return f"{self.PREFIX}{tenant_id}:{report}:{scope}:{digest}"

    def ttl_for(self, report: str) -> int:
        mapping = {
            "spend_trends": settings.analytics_cache_ttl_quarterly,
            "quarter_comparison": settings.analytics_cache_ttl_quarterly,
            "vendor_breakdown": settings.analytics_cache_ttl_vendor,
            "vendor_growth": settings.analytics_cache_ttl_vendor,
            "department_analysis": settings.analytics_cache_ttl_department,
            "department_trends": settings.analytics_cache_ttl_department,
            "category_breakdown": settings.analytics_cache_ttl_department,
            "policy_violations": settings.analytics_cache_ttl_default,
            "approval_health": settings.analytics_cache_ttl_default,
            "forecast": settings.analytics_cache_ttl_default,
        }
        return mapping.get(report, settings.analytics_cache_ttl_default)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        client = self._get_client()
        if not client:
            return None
        try:
            raw = client.get(key)
            if raw:
                data = json.loads(raw)
                data["_cache"] = {"hit": True, "key": key}
                return data
        except Exception as exc:
            logger.debug("cache get failed: %s", exc)
        return None

    def set(self, key: str, value: Dict[str, Any], *, ttl: int) -> None:
        client = self._get_client()
        if not client:
            return
        try:
            payload = {k: v for k, v in value.items() if k != "_cache"}
            client.setex(key, ttl, json.dumps(payload, default=str))
        except Exception as exc:
            logger.debug("cache set failed: %s", exc)

    def get_or_compute(
        self,
        report: str,
        *,
        tenant_id: int,
        user: User,
        params: Optional[Dict[str, Any]],
        compute_fn: Callable[[], Dict[str, Any]],
    ) -> Dict[str, Any]:
        key = self.build_key(report, tenant_id=tenant_id, user=user, params=params)
        hit = self.get(key)
        if hit is not None:
            return hit
        result = compute_fn()
        if isinstance(result, dict):
            result["_cache"] = {"hit": False, "key": key}
            self.set(key, result, ttl=self.ttl_for(report))
        return result

    def invalidate_prefix(self, tenant_id: int, report: Optional[str] = None) -> int:
        client = self._get_client()
        if not client:
            return 0
        pattern = f"{self.PREFIX}{tenant_id}:{report or '*'}:*"
        deleted = 0
        try:
            for key in client.scan_iter(match=pattern, count=100):
                client.delete(key)
                deleted += 1
        except Exception as exc:
            logger.warning("cache invalidate failed: %s", exc)
        return deleted
