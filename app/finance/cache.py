"""In-process analytics result cache (sync)."""
import hashlib
import json
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

from app.config import settings
from app.finance.scope import is_company_scope
from app.models import User

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AnalyticsCache:
    """
    Cache expensive finance analytics (quarterly trends, vendors, departments).
    Falls through to compute on miss or when caching is disabled.
    """

    PREFIX = "finance:analytics:"

    def __init__(self) -> None:
        self._enabled = settings.analytics_cache_enabled
        self._entries: Dict[str, Tuple[float, Dict[str, Any]]] = {}

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
        if not self._enabled:
            return None
        entry = self._entries.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            self._entries.pop(key, None)
            return None
        data = dict(value)
        data["_cache"] = {"hit": True, "key": key}
        return data

    def set(self, key: str, value: Dict[str, Any], *, ttl: int) -> None:
        if not self._enabled:
            return
        payload = {k: v for k, v in value.items() if k != "_cache"}
        self._entries[key] = (time.time() + ttl, payload)

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
        pattern = f"{self.PREFIX}{tenant_id}:{report or ''}"
        deleted = 0
        for key in list(self._entries):
            if report:
                if key.startswith(pattern):
                    self._entries.pop(key, None)
                    deleted += 1
            elif key.startswith(f"{self.PREFIX}{tenant_id}:"):
                self._entries.pop(key, None)
                deleted += 1
        return deleted
