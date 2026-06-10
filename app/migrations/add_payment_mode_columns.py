"""Add payment_method to policies and claims."""
from sqlalchemy import text

from app.database import engine


def run():
    stmts = [
        "ALTER TABLE policies ADD COLUMN IF NOT EXISTS payment_method VARCHAR(32)",
        "ALTER TABLE policies ADD COLUMN IF NOT EXISTS allowed_payment_modes JSONB",
        "ALTER TABLE claims ADD COLUMN IF NOT EXISTS payment_method VARCHAR(32)",
    ]
    with engine.connect() as conn:
        for sql in stmts:
            conn.execute(text(sql))
        conn.commit()
    print("Added payment_method columns to policies and claims.")


if __name__ == "__main__":
    run()
