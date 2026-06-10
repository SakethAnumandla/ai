"""Shared state for API route smoke tests (avoids circular imports)."""
from __future__ import annotations

from typing import Optional

from tests.seed_data import SeedIds

CURRENT_SEED: Optional[SeedIds] = None
