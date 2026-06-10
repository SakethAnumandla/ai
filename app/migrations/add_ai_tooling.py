"""Tool idempotency table for duplicate-action prevention."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_idempotency_keys (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                idempotency_key VARCHAR(128) NOT NULL,
                action_type VARCHAR(64) NOT NULL,
                response_payload JSONB NOT NULL DEFAULT '{}',
                status VARCHAR(32) DEFAULT 'completed',
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_idempotency_tenant_user_key_action
            ON ai_idempotency_keys (tenant_id, user_id, idempotency_key, action_type)
        """))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("AI tooling migration applied.")
