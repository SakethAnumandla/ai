"""Pre-Phase 7 executive hardening: immutable snapshots, report audit, alert priority."""
from sqlalchemy import text

from app.database import engine


def upgrade():
    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE analytics_snapshots
            ADD COLUMN IF NOT EXISTS immutable BOOLEAN NOT NULL DEFAULT FALSE
        """))
        conn.execute(text("""
            ALTER TABLE analytics_snapshots
            ADD COLUMN IF NOT EXISTS is_executive BOOLEAN NOT NULL DEFAULT FALSE
        """))
        conn.execute(text("""
            ALTER TABLE analytics_snapshots
            ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)
        """))
        conn.execute(text("""
            ALTER TABLE analytics_snapshots
            ADD COLUMN IF NOT EXISTS frozen_at TIMESTAMPTZ
        """))

        conn.execute(text("""
            ALTER TABLE kpi_alerts
            ADD COLUMN IF NOT EXISTS priority VARCHAR(16) DEFAULT 'medium'
        """))
        conn.execute(text("""
            ALTER TABLE kpi_alerts
            ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(64)
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_kpi_alerts_tenant_priority "
            "ON kpi_alerts (tenant_id, priority, status)"
        ))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS finance_report_access_audits (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id),
                job_id INTEGER NOT NULL,
                report_type VARCHAR(64) NOT NULL,
                report_version VARCHAR(64),
                file_format VARCHAR(16) NOT NULL,
                file_path TEXT NOT NULL,
                ip_address VARCHAR(64),
                user_agent VARCHAR(512),
                accessed_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_finance_report_audit_tenant_time "
            "ON finance_report_access_audits (tenant_id, accessed_at DESC)"
        ))
        conn.commit()


if __name__ == "__main__":
    upgrade()
    print("Pre-Phase 7 executive hardening migration applied.")
