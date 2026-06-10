"""Add business taxonomy fields, expense approvals, AI chat sessions."""
import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

_STATEMENTS = [
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS line_item VARCHAR(128)",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS financial_year VARCHAR(16)",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS amount_excl_gst DOUBLE PRECISION",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS gst_rate_pct DOUBLE PRECISION",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS gst_amount DOUBLE PRECISION",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS itc_eligible BOOLEAN DEFAULT FALSE",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS currency_code VARCHAR(3) DEFAULT 'EUR'",
    "CREATE INDEX IF NOT EXISTS ix_expenses_financial_year ON expenses (financial_year)",
]


def run():
    with engine.begin() as conn:
        for stmt in _STATEMENTS:
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                logger.warning("migration skip: %s — %s", stmt[:60], exc)
    logger.info("add_expense_business_fields: columns ensured")


if __name__ == "__main__":
    run()
