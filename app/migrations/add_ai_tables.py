"""Create AI foundation tables: conversations, memory, summaries, actions."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_id VARCHAR(64) NOT NULL,
                role VARCHAR(32) NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB DEFAULT '{}',
                token_count INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_conversations_tenant_user "
            "ON ai_conversations (tenant_id, user_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_conversations_session "
            "ON ai_conversations (tenant_id, user_id, session_id, created_at)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_memory (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                memory_type VARCHAR(32) NOT NULL,
                memory_key VARCHAR(255) NOT NULL,
                value JSONB NOT NULL DEFAULT '{}',
                importance REAL DEFAULT 0.5,
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ
            )
        """))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_memory_tenant_user_key "
            "ON ai_memory (tenant_id, user_id, memory_key)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_memory_tenant_user "
            "ON ai_memory (tenant_id, user_id)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_summaries (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_id VARCHAR(64) NOT NULL,
                summary_text TEXT NOT NULL,
                token_count_before INTEGER DEFAULT 0,
                token_count_after INTEGER DEFAULT 0,
                model VARCHAR(64),
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_summaries_session "
            "ON ai_summaries (tenant_id, user_id, session_id, created_at DESC)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_actions (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_id VARCHAR(64),
                action_type VARCHAR(32) NOT NULL,
                tool_name VARCHAR(128),
                model VARCHAR(64),
                payload JSONB DEFAULT '{}',
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                status VARCHAR(32) DEFAULT 'success',
                error_message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_actions_tenant_user "
            "ON ai_actions (tenant_id, user_id, created_at DESC)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_ai_actions_session "
            "ON ai_actions (tenant_id, user_id, session_id)"
        ))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("AI tables migration applied.")
