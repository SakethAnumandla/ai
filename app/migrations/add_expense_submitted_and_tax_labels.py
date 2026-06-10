"""Add submitted expense status support and simplified tax label columns."""
from sqlalchemy import text

from app.database import engine


def run():
    stmts = [
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'expensestatus' AND e.enumlabel = 'submitted'
            ) THEN
                ALTER TYPE expensestatus ADD VALUE IF NOT EXISTS 'submitted';
            END IF;
        EXCEPTION
            WHEN undefined_object THEN
                NULL;
        END $$;
        """,
        "ALTER TABLE expense_taxes ADD COLUMN IF NOT EXISTS tax_label VARCHAR(64)",
        "ALTER TABLE expense_taxes ADD COLUMN IF NOT EXISTS calculation_type VARCHAR(16) DEFAULT 'fixed_value'",
        "ALTER TYPE expensestatus ADD VALUE IF NOT EXISTS 'SUBMITTED'",
    ]
    with engine.connect() as conn:
        for sql in stmts:
            conn.execute(text(sql))
        conn.commit()
    print("Migration add_expense_submitted_and_tax_labels completed.")


if __name__ == "__main__":
    run()
