"""Add ocr_batches.result_summary for batch duplicate/skip reporting."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(
            text(
                "ALTER TABLE ocr_batches "
                "ADD COLUMN IF NOT EXISTS result_summary JSONB"
            )
        )
        conn.commit()


if __name__ == "__main__":
    upgrade()
