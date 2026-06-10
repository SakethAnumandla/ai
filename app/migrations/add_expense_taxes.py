"""Add expense_taxes table and expense country/subtotal columns."""
from sqlalchemy import text

from app.database import engine


def run():
    stmts = [
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS country_code VARCHAR(2) DEFAULT 'IN'",
        "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS subtotal DOUBLE PRECISION",
        """
        CREATE TABLE IF NOT EXISTS expense_taxes (
            id SERIAL PRIMARY KEY,
            expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
            country_code VARCHAR(2) NOT NULL DEFAULT 'IN',
            tax_regime VARCHAR(32) NOT NULL DEFAULT 'india_gst',
            tax_type VARCHAR(32) NOT NULL,
            tax_rate DOUBLE PRECISION,
            taxable_amount DOUBLE PRECISION,
            cgst DOUBLE PRECISION DEFAULT 0,
            sgst DOUBLE PRECISION DEFAULT 0,
            igst DOUBLE PRECISION DEFAULT 0,
            vat DOUBLE PRECISION DEFAULT 0,
            tax_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
            recoverable BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_expense_taxes_expense_id ON expense_taxes (expense_id)",
        "CREATE INDEX IF NOT EXISTS ix_expense_taxes_tax_type ON expense_taxes (tax_type)",
    ]
    with engine.connect() as conn:
        for sql in stmts:
            conn.execute(text(sql))
        conn.commit()
    print("Migration add_expense_taxes completed.")


if __name__ == "__main__":
    run()
