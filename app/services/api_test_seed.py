"""Idempotent API fixture bootstrap for Postman/Newman (re-export from test seed module)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from tests.seed_data import SeedIds, ensure_api_fixtures

__all__ = ["SeedIds", "ensure_api_fixtures"]
