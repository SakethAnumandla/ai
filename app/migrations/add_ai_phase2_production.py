"""Phase 2 production tables: confirmations, usage, permissions, prompt versions."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_confirmations (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_id VARCHAR(64) NOT NULL,
                confirmation_token VARCHAR(64) NOT NULL UNIQUE,
                tool_name VARCHAR(128) NOT NULL,
                arguments JSONB NOT NULL DEFAULT '{}',
                summary_message TEXT NOT NULL,
                status VARCHAR(32) DEFAULT 'pending',
                expires_at TIMESTAMPTZ NOT NULL,
                confirmed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_confirmations_token "
            "ON ai_confirmations (confirmation_token)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_confirmations_user_pending "
            "ON ai_confirmations (tenant_id, user_id, session_id, status)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tenant_ai_usage (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                usage_date DATE NOT NULL,
                prompt_tokens BIGINT DEFAULT 0,
                completion_tokens BIGINT DEFAULT 0,
                total_tokens BIGINT DEFAULT 0,
                estimated_cost_usd REAL DEFAULT 0,
                request_count INTEGER DEFAULT 0,
                tool_invocation_count INTEGER DEFAULT 0,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (tenant_id, usage_date)
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_tool_permissions (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER,
                role VARCHAR(64) NOT NULL,
                tool_name VARCHAR(128) NOT NULL,
                action VARCHAR(64) NOT NULL DEFAULT 'execute',
                scope VARCHAR(64) NOT NULL DEFAULT 'own',
                allowed BOOLEAN DEFAULT TRUE,
                UNIQUE (tenant_id, role, tool_name, action, scope)
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_prompt_versions (
                id SERIAL PRIMARY KEY,
                prompt_key VARCHAR(128) NOT NULL UNIQUE,
                version INTEGER NOT NULL DEFAULT 1,
                role_target VARCHAR(64),
                content TEXT NOT NULL,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))

        conn.execute(text(
            "ALTER TABLE ai_actions ADD COLUMN IF NOT EXISTS parent_audit_id INTEGER"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_actions_parent ON ai_actions (parent_audit_id)"
        ))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("Phase 2 production migration applied.")
