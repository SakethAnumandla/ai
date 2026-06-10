"""Clear AI-generated data from Redis (and optional PostgreSQL cleanup for legacy rows).

Removes from Redis (keys prefixed ``ai:``):
- Chat messages, long-term memory hash, session summaries, prompt/tool audit actions,
  memory-governance audit events, draft/intent/workflow session keys.

PostgreSQL cleanup (when ``--user-id`` is used):
- AI tables that remain on Postgres: confirmations, idempotency, dead letters, usage, etc.
- Skips tables already removed by ``app/migrations/drop_ai_tables_moved_to_redis.py``.
- OCR bills/batches and dev-user expenses (typical AI/OCR test data)
- Claims/approvals tied to those expenses
- Processing jobs and voice transcription audits

Preserves: users, policies, wallets (balances reset for affected users), seed config tables.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from app.database import engine
from app.config import settings


AI_RUNTIME_TABLES = [
    "ai_job_dead_letters",
    "ai_confirmations",
    "ai_idempotency_keys",
    "tenant_ai_usage",
]


def _table_exists(conn, table: str) -> bool:
    q = text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = :name)"
    )
    return bool(conn.execute(q, {"name": table}).scalar())
def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0


def clear_postgres(*, user_id: int | None = 1) -> dict[str, int]:
    """Delete AI/OCR/test expenses. If user_id is None, only clears AI runtime tables."""
    removed: dict[str, int] = {}

    with engine.begin() as conn:
        for table in AI_RUNTIME_TABLES:
            if not _table_exists(conn, table):
                continue
            n = _count(conn, table)
            conn.execute(text(f"DELETE FROM {table}"))
            if n:
                removed[table] = n

        n_voice = _count(conn, "voice_transcription_audits")
        conn.execute(text("DELETE FROM voice_transcription_audits"))
        removed["voice_transcription_audits"] = n_voice

        n_jobs = _count(conn, "processing_jobs")
        conn.execute(text("DELETE FROM processing_jobs"))
        removed["processing_jobs"] = n_jobs

        if user_id is not None:
            claim_ids = [
                r[0]
                for r in conn.execute(
                    text("SELECT id FROM claims WHERE user_id = :uid"),
                    {"uid": user_id},
                ).fetchall()
            ]
            removed["claims"] = len(claim_ids)
            if claim_ids:
                conn.execute(
                    text("DELETE FROM claim_approvals WHERE claim_id = ANY(:ids)"),
                    {"ids": claim_ids},
                )
                conn.execute(
                    text("DELETE FROM claims WHERE user_id = :uid"),
                    {"uid": user_id},
                )

            n_ocr_bills = conn.execute(
                text("SELECT COUNT(*) FROM ocr_bills WHERE user_id = :uid"),
                {"uid": user_id},
            ).scalar() or 0
            conn.execute(
                text("DELETE FROM ocr_bills WHERE user_id = :uid"),
                {"uid": user_id},
            )
            removed["ocr_bills"] = n_ocr_bills

            n_batches = conn.execute(
                text("SELECT COUNT(*) FROM ocr_batches WHERE user_id = :uid"),
                {"uid": user_id},
            ).scalar() or 0
            conn.execute(
                text("DELETE FROM ocr_batches WHERE user_id = :uid"),
                {"uid": user_id},
            )
            removed["ocr_batches"] = n_batches

            expense_ids = [
                r[0]
                for r in conn.execute(
                    text("SELECT id FROM expenses WHERE user_id = :uid"),
                    {"uid": user_id},
                ).fetchall()
            ]
            if expense_ids:
                conn.execute(
                    text("DELETE FROM wallet_transactions WHERE expense_id = ANY(:ids)"),
                    {"ids": expense_ids},
                )
                conn.execute(
                    text("DELETE FROM expenses WHERE user_id = :uid"),
                    {"uid": user_id},
                )
            removed["expenses"] = len(expense_ids)

            conn.execute(
                text(
                    """
                    UPDATE wallets
                    SET balance = 0, total_income = 0, total_expense = 0
                    WHERE user_id = :uid
                    """
                ),
                {"uid": user_id},
            )

    return removed


async def clear_redis() -> int:
    try:
        import redis.asyncio as aioredis
    except ImportError:
        return 0

    client = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        await client.ping()
    except Exception:
        return 0

    deleted = 0
    async for key in client.scan_iter(match="ai:*", count=200):
        await client.delete(key)
        deleted += 1
    await client.aclose()
    return deleted


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Clear AI-generated DB/Redis data")
    parser.add_argument(
        "--user-id",
        type=int,
        default=1,
        help="Dev user whose expenses/OCR/claims to wipe (default: 1). Use --all-users for AI tables only.",
    )
    parser.add_argument(
        "--ai-only",
        action="store_true",
        help="Only clear AI runtime tables + Redis; keep expenses/OCR.",
    )
    args = parser.parse_args()

    user_id = None if args.ai_only else args.user_id
    removed = clear_postgres(user_id=user_id)
    redis_deleted = asyncio.run(clear_redis())

    print("Cleared PostgreSQL:")
    for table, count in removed.items():
        if count:
            print(f"  {table}: {count} row(s)")
    if not any(removed.values()):
        print("  (no rows removed)")
    print(f"Cleared Redis: {redis_deleted} key(s) matching ai:*")


if __name__ == "__main__":
    main()
