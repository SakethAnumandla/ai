"""AI improvements: observability columns on ai_actions, ai_model_config table."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE ai_actions ADD COLUMN IF NOT EXISTS request_id VARCHAR(64)"
        ))
        conn.execute(text(
            "ALTER TABLE ai_actions ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_actions_request_id ON ai_actions (request_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_actions_trace_id ON ai_actions (trace_id)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_model_config (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                model_name VARCHAR(64) NOT NULL,
                temperature REAL DEFAULT 0.2,
                enabled_tools JSONB DEFAULT '[]',
                max_tokens INTEGER DEFAULT 4096,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_model_config_tenant "
            "ON ai_model_config (tenant_id, active)"
        ))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("AI improvements migration applied.")
