"""Add submitted_by name/role columns on expenses."""
import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

_STATEMENTS = [
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS submitted_by_name VARCHAR(128)",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS submitted_by_role VARCHAR(128)",
]


def run():
    with engine.begin() as conn:
        for stmt in _STATEMENTS:
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                logger.warning("migration skip: %s — %s", stmt[:60], exc)
    logger.info("add_expense_submitted_by: columns ensured")


if __name__ == "__main__":
    run()
