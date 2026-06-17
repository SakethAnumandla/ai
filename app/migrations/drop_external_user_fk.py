"""Allow external Bizwy user_id values without a local users row."""
import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

# Known constraint names (PostgreSQL default naming) — run first for reliability.
_EXPLICIT_DROPS = (
    ("expenses", "expenses_user_id_fkey"),
    ("wallets", "wallets_user_id_fkey"),
    ("ocr_batches", "ocr_batches_user_id_fkey"),
    ("ocr_bills", "ocr_bills_user_id_fkey"),
    ("budgets", "budgets_user_id_fkey"),
    ("claims", "claims_user_id_fkey"),
    ("ai_chat_sessions", "ai_chat_sessions_user_id_fkey"),
    ("ai_conversations", "ai_conversations_user_id_fkey"),
    ("ai_memory", "ai_memory_user_id_fkey"),
    ("expense_approvals", "expense_approvals_approver_id_fkey"),
    ("claim_approvals", "claim_approvals_approver_id_fkey"),
    ("expenses", "expenses_approved_by_fkey"),
)

_TABLES = (
    "expenses",
    "wallets",
    "ocr_batches",
    "ocr_bills",
    "budgets",
    "claims",
    "ai_chat_sessions",
    "ai_conversations",
    "ai_memory",
    "ai_actions",
    "ai_confirmations",
    "ai_summaries",
    "ai_memory_audit_events",
    "ai_idempotency_keys",
    "ai_job_dead_letters",
    "analytics_snapshots",
    "processing_jobs",
    "voice_transcription_audits",
)


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :t LIMIT 1"
        ),
        {"t": table},
    ).first()
    return row is not None


def _drop_explicit(conn, table: str, constraint: str) -> None:
    if not _table_exists(conn, table):
        return
    conn.execute(
        text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{constraint}"')
    )
    logger.info("dropped constraint %s on %s", constraint, table)


def _drop_user_fk_dynamic(conn, table: str) -> None:
    if not _table_exists(conn, table):
        return
    conn.execute(
        text(
            f"""
            DO $$ DECLARE r RECORD;
            BEGIN
              FOR r IN (
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                WHERE c.conrelid = '{table}'::regclass
                  AND c.contype = 'f'
                  AND a.attname = 'user_id'
              ) LOOP
                EXECUTE format(
                  'ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I',
                  '{table}', r.conname
                );
              END LOOP;
            END $$;
            """
        )
    )


def _drop_column_fk_dynamic(conn, table: str, column: str) -> None:
    if not _table_exists(conn, table):
        return
    conn.execute(
        text(
            f"""
            DO $$ DECLARE r RECORD;
            BEGIN
              FOR r IN (
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                WHERE c.conrelid = '{table}'::regclass
                  AND c.contype = 'f'
                  AND a.attname = '{column}'
              ) LOOP
                EXECUTE format(
                  'ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I',
                  '{table}', r.conname
                );
              END LOOP;
            END $$;
            """
        )
    )


def expenses_user_id_fk_present() -> bool:
    """True when expenses.user_id still references local users (blocks external Bizwy ids)."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = 'expenses_user_id_fkey' LIMIT 1"
            )
        ).first()
        return row is not None


def run() -> None:
    """Idempotent — safe to run on every startup."""
    # One transaction per step so a missing table never rolls back prior drops.
    for table, constraint in _EXPLICIT_DROPS:
        try:
            with engine.begin() as conn:
                _drop_explicit(conn, table, constraint)
        except Exception as exc:
            logger.warning("drop_explicit failed %s.%s: %s", table, constraint, exc)

    for table in _TABLES:
        try:
            with engine.begin() as conn:
                _drop_user_fk_dynamic(conn, table)
        except Exception as exc:
            logger.warning("drop user_id fk failed on %s: %s", table, exc)

    for table, column in (
        ("expense_approvals", "approver_id"),
        ("claim_approvals", "approver_id"),
        ("expenses", "approved_by"),
    ):
        try:
            with engine.begin() as conn:
                _drop_column_fk_dynamic(conn, table, column)
        except Exception as exc:
            logger.warning("drop %s fk failed on %s: %s", column, table, exc)

    logger.info("drop_external_user_fk complete")
