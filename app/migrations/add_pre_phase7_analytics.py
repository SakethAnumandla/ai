"""Pre-Phase 7: analytics snapshots and KPI alerts."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS analytics_snapshots (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                snapshot_type VARCHAR(64) NOT NULL,
                period_label VARCHAR(32) NOT NULL,
                department VARCHAR(32),
                payload JSONB NOT NULL DEFAULT '{}',
                summary_text TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_analytics_snapshots_tenant_type "
            "ON analytics_snapshots (tenant_id, snapshot_type, created_at DESC)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS kpi_alerts (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                alert_type VARCHAR(64) NOT NULL,
                severity VARCHAR(16) DEFAULT 'medium',
                title VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                details JSONB DEFAULT '{}',
                status VARCHAR(16) DEFAULT 'open',
                acknowledged_by INTEGER REFERENCES users(id),
                acknowledged_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_kpi_alerts_tenant_status "
            "ON kpi_alerts (tenant_id, status, created_at DESC)"
        ))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("Pre-Phase 7 analytics migration applied.")
