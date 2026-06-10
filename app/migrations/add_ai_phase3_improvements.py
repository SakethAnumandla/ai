"""Phase 3 prep: dead letter queue for failed AI jobs."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_job_dead_letters (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_id VARCHAR(64),
                job_type VARCHAR(128) NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}',
                error_message TEXT,
                status VARCHAR(32) DEFAULT 'failed',
                retry_count INTEGER DEFAULT 0,
                trace_id VARCHAR(64),
                request_id VARCHAR(64),
                last_retry_at TIMESTAMPTZ,
                resolved_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_dlq_tenant_status "
            "ON ai_job_dead_letters (tenant_id, status, created_at DESC)"
        ))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("Phase 3 improvements migration applied.")
