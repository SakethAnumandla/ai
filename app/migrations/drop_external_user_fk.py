"""Allow external Bizwy user_id values without a local users row."""
import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

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
    "finance_report_access",
    "finance_kpi_alerts",
)


def _drop_user_fk(conn, table: str) -> None:
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


def _drop_approver_fk(conn, table: str, column: str) -> None:
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


def run() -> None:
    with engine.begin() as conn:
        for table in _TABLES:
            try:
                _drop_user_fk(conn, table)
            except Exception as exc:
                logger.debug("drop user_id fk skip %s: %s", table, exc)
        for table, column in (
            ("expense_approvals", "approver_id"),
            ("claim_approvals", "approver_id"),
            ("expenses", "approved_by"),
        ):
            try:
                _drop_approver_fk(conn, table, column)
            except Exception as exc:
                logger.debug("drop %s fk skip %s: %s", column, table, exc)
    logger.info("drop_external_user_fk complete")
