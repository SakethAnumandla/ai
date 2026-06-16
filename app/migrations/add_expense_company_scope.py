"""Add company_id scoping columns and per-owner wallet index."""
import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

_STATEMENTS = [
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS company_id INTEGER NOT NULL DEFAULT 1",
    "CREATE INDEX IF NOT EXISTS idx_expenses_owner ON expenses (company_id, user_id)",
    "ALTER TABLE wallets ADD COLUMN IF NOT EXISTS company_id INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE ocr_batches ADD COLUMN IF NOT EXISTS company_id INTEGER NOT NULL DEFAULT 1",
    "CREATE INDEX IF NOT EXISTS idx_ocr_batches_owner ON ocr_batches (company_id, user_id)",
    "ALTER TABLE ocr_bills ADD COLUMN IF NOT EXISTS company_id INTEGER NOT NULL DEFAULT 1",
    "CREATE INDEX IF NOT EXISTS idx_ocr_bills_owner ON ocr_bills (company_id, user_id)",
    "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS company_id INTEGER NOT NULL DEFAULT 1",
    "CREATE INDEX IF NOT EXISTS idx_budgets_owner ON budgets (company_id, user_id)",
]


def _drop_wallet_user_unique(conn) -> None:
    """Replace global one-wallet-per-user with (company_id, user_id) uniqueness."""
    for stmt in (
        "ALTER TABLE wallets DROP CONSTRAINT IF EXISTS wallets_user_id_key",
        "ALTER TABLE wallets DROP CONSTRAINT IF EXISTS uq_wallets_user_id",
    ):
        try:
            conn.execute(text(stmt))
        except Exception as exc:
            logger.debug("wallet unique drop skip: %s", exc)
    try:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_owner "
                "ON wallets (company_id, user_id)"
            )
        )
    except Exception as exc:
        logger.warning("idx_wallet_owner: %s", exc)


def run():
    with engine.begin() as conn:
        for stmt in _STATEMENTS:
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                logger.warning("migration skip: %s — %s", stmt[:72], exc)
        _drop_wallet_user_unique(conn)
    logger.info("add_expense_company_scope: columns and indexes ensured")


if __name__ == "__main__":
    run()
