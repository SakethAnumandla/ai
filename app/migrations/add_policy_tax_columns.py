"""Add tax regime columns to policies table."""
from sqlalchemy import text

from app.database import engine


def run():
    stmts = [
        "ALTER TABLE policies ADD COLUMN IF NOT EXISTS country_code VARCHAR(2) DEFAULT 'IN'",
        "ALTER TABLE policies ADD COLUMN IF NOT EXISTS tax_regime VARCHAR(32) DEFAULT 'india_gst'",
        "ALTER TABLE policies ADD COLUMN IF NOT EXISTS applicable_tax_types JSONB",
        "ALTER TABLE policies ADD COLUMN IF NOT EXISTS tax_inclusive BOOLEAN DEFAULT FALSE",
    ]
    with engine.connect() as conn:
        for sql in stmts:
            conn.execute(text(sql))
        conn.commit()
    print("Added policy tax columns.")


if __name__ == "__main__":
    run()
