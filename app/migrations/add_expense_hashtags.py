"""Add expenses.hashtags JSON column. Run: python -m app.migrations.add_expense_hashtags"""
from sqlalchemy import text

from app.database import engine


def run():
    with engine.connect() as conn:
        conn.execute(
            text(
                "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS hashtags JSONB DEFAULT '[]'::jsonb"
            )
        )
        conn.commit()
    print("Added expenses.hashtags column (if missing).")


if __name__ == "__main__":
    run()
