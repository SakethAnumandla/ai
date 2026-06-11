"""Idempotent API test fixtures — dynamic IDs for Postman/Newman (no hardcoded paths)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api-test", tags=["api-test"])

MARKER_POLICY_ID = "POL-API-TEST-001"


def _bootstrap_enabled() -> bool:
    return bool(getattr(settings, "enable_api_test_bootstrap", True))


@router.post("/bootstrap")
@router.get("/bootstrap")
async def bootstrap_api_fixtures(db: Session = Depends(get_db)):
    """
    Ensure smoke-test entities exist and return their live database IDs.

    Safe to call before Newman/Postman runs — creates fixtures only when missing
    (does not wipe existing data). IDs are always read from the database response.
    """
    if not _bootstrap_enabled():
        raise HTTPException(status_code=404, detail="API test bootstrap is disabled")

    from app.services.api_test_seed import ensure_api_fixtures

    ids = ensure_api_fixtures(db)
    payload = {field: getattr(ids, field) for field in ids.__dataclass_fields__}
    return {
        "status": "ready",
        "message": "Use returned IDs as Postman collection variables (never hardcode).",
        "ids": payload,
    }
