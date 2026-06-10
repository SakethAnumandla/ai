"""Deprecated shim — runs drop_all_ai_postgres_tables."""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.migrations.drop_all_ai_postgres_tables import upgrade  # noqa: E402

if __name__ == "__main__":
    upgrade()
    print("Dropped all AI-related Postgres tables (if they existed).")
