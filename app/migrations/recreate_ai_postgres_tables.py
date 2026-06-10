"""
Recreate all AI-related PostgreSQL tables (after Redis-only drop).

Run once:

    docker compose run --rm --no-deps backend python app/migrations/recreate_ai_postgres_tables.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def upgrade() -> None:
    from app.migrations import add_ai_tables
    from app.migrations import add_ai_tooling
    from app.migrations import add_ai_improvements
    from app.migrations import add_ai_phase2_production
    from app.migrations import add_ai_memory_governance
    from app.migrations import add_ai_phase3_improvements

    add_ai_tables.upgrade()
    add_ai_tooling.upgrade()
    add_ai_improvements.upgrade()
    add_ai_phase2_production.upgrade()
    add_ai_memory_governance.upgrade()
    add_ai_phase3_improvements.upgrade()


if __name__ == "__main__":
    upgrade()
    print("All AI Postgres tables created (or already present).")
