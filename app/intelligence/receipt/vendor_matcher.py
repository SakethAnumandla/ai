"""Normalized vendor matching against user history and preferences."""
import re
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.ai.memory.repository import AIRepository
from app.ai.schemas.common import TenantUserContext
from app.models import Expense


def normalize_vendor(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = name.strip().lower()
    s = re.sub(r"\s+(pvt|ltd|limited|inc|llc)\.?\s*$", "", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


class VendorMatcher:
    def __init__(self, db: Session, repository: Optional[AIRepository] = None):
        self._db = db
        self._repo = repository

    def match(
        self,
        ctx: TenantUserContext,
        merchant: Optional[str],
    ) -> Tuple[Optional[str], Optional[str], float]:
        """
        Returns (display_name, normalized_key, confidence).
        """
        norm = normalize_vendor(merchant)
        if not norm:
            return merchant, None, 0.0

        if self._repo:
            rows = self._repo.fetch_memories(ctx, limit=50)
            for row in rows:
                if row.memory_key.startswith("preference:vendor:"):
                    val = row.value or {}
                    vn = normalize_vendor(val.get("vendor_name"))
                    if vn == norm:
                        return val.get("vendor_name", merchant), norm, 0.9

        recent = (
            self._db.query(Expense)
            .filter(Expense.user_id == ctx.user_id, Expense.vendor_name.isnot(None))
            .order_by(Expense.created_at.desc())
            .limit(100)
            .all()
        )
        for exp in recent:
            vn = normalize_vendor(exp.vendor_name)
            if vn == norm:
                return exp.vendor_name, norm, 0.85
            if vn and norm in vn or vn in norm:
                return exp.vendor_name, vn, 0.7

        return merchant, norm, 0.4
