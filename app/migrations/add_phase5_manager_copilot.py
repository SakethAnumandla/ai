"""Phase 5: approval escalations for manager copilot."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS approval_escalations (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
                approval_id INTEGER REFERENCES claim_approvals(id) ON DELETE SET NULL,
                escalated_by INTEGER NOT NULL REFERENCES users(id),
                target_role VARCHAR(32) NOT NULL DEFAULT 'finance_admin',
                reason TEXT NOT NULL,
                risk_score DOUBLE PRECISION,
                risk_flags JSONB DEFAULT '[]',
                status VARCHAR(32) NOT NULL DEFAULT 'open',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                resolved_at TIMESTAMPTZ
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_escalations_tenant_status "
            "ON approval_escalations (tenant_id, status, created_at DESC)"
        ))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("Phase 5 manager copilot migration applied.")
