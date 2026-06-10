"""Migration: expense_files, ocr_batches, ocr_bills.batch_id"""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS expense_files (
                id SERIAL PRIMARY KEY,
                expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
                file_data BYTEA NOT NULL,
                file_name VARCHAR NOT NULL,
                file_size INTEGER NOT NULL,
                mime_type VARCHAR NOT NULL,
                file_hash VARCHAR(64),
                thumbnail_data BYTEA,
                is_primary BOOLEAN DEFAULT FALSE,
                page_number INTEGER,
                uploaded_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_expense_files_expense_id ON expense_files (expense_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_expense_files_hash ON expense_files (file_hash)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ocr_batches (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                batch_name VARCHAR,
                total_files INTEGER DEFAULT 0,
                processed_files INTEGER DEFAULT 0,
                status VARCHAR DEFAULT 'processing',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
        """))

        conn.execute(text("""
            ALTER TABLE ocr_bills
            ADD COLUMN IF NOT EXISTS batch_id INTEGER REFERENCES ocr_batches(id) ON DELETE SET NULL
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ocr_bills_batch_id ON ocr_bills (batch_id)"
        ))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("Migration applied.")
