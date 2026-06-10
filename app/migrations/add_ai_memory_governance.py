"""Memory governance: tenant policies and preference audit history."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_tenant_memory_policies (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL UNIQUE,
                allow_preference_learning BOOLEAN NOT NULL DEFAULT TRUE,
                allow_behavioral_memory BOOLEAN NOT NULL DEFAULT TRUE,
                allow_long_term_storage BOOLEAN NOT NULL DEFAULT TRUE,
                allow_entity_graph BOOLEAN NOT NULL DEFAULT TRUE,
                allow_anomaly_detection BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_memory_audit_events (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                memory_key VARCHAR(255) NOT NULL,
                change_type VARCHAR(64) NOT NULL,
                source VARCHAR(128),
                confidence_before DOUBLE PRECISION,
                confidence_after DOUBLE PRECISION,
                before_snapshot JSONB DEFAULT '{}',
                after_snapshot JSONB DEFAULT '{}',
                evidence JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_mem_audit_tenant_user_time "
            "ON ai_memory_audit_events (tenant_id, user_id, created_at DESC)"
        ))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("AI memory governance migration applied.")
