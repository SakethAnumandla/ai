"""Phase 4: processing jobs + voice transcription audit."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS processing_jobs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                tenant_id INTEGER NOT NULL,
                job_type VARCHAR(64) NOT NULL,
                status VARCHAR(32) DEFAULT 'pending',
                celery_task_id VARCHAR(128),
                payload JSONB DEFAULT '{}',
                result JSONB DEFAULT '{}',
                error_message TEXT,
                progress VARCHAR(255),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_processing_jobs_user_status "
            "ON processing_jobs (user_id, status, created_at DESC)"
        ))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS voice_transcription_audits (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                tenant_id INTEGER NOT NULL,
                job_id INTEGER REFERENCES processing_jobs(id) ON DELETE SET NULL,
                session_id VARCHAR(64),
                file_name VARCHAR(255),
                file_size INTEGER,
                language VARCHAR(16),
                model VARCHAR(64),
                transcript_preview TEXT,
                duration_seconds DOUBLE PRECISION,
                latency_ms INTEGER DEFAULT 0,
                status VARCHAR(32) DEFAULT 'success',
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("Phase 4 intelligence migration applied.")
