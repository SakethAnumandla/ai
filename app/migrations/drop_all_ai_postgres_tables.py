"""
Drop every AI-related Postgres table (chat/memory now in Redis).

Run from repo root / Docker (WORKDIR /app):

    docker compose run --rm --no-deps backend python app/migrations/drop_all_ai_postgres_tables.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sqlalchemy import text

from app.database import engine

# Child / dependent tables first; CASCADE handles leftovers.
AI_TABLES = [
    "ai_memory_audit_events",
    "ai_summaries",
    "ai_conversations",
    "ai_memory",
    "ai_actions",
    "ai_job_dead_letters",
    "ai_confirmations",
    "ai_idempotency_keys",
    "ai_model_config",
    "ai_tool_permissions",
    "ai_prompt_versions",
    "ai_tenant_memory_policies",
    "tenant_ai_usage",
    "voice_transcription_audits",
]


def upgrade() -> None:
    with engine.begin() as conn:
        for table in AI_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))


if __name__ == "__main__":
    upgrade()
    print(f"Dropped {len(AI_TABLES)} AI-related Postgres tables (if they existed).")
