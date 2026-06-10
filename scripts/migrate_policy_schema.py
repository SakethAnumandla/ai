"""
Apply policy/claims schema changes on an existing database.
Run: python -m scripts.migrate_policy_schema
"""
from sqlalchemy import inspect, text

from app.database import engine, Base
import app.models  # noqa: F401


def column_exists(table: str, column: str) -> bool:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def run():
    with engine.connect() as conn:
        if column_exists("users", "id"):
            for col, ddl in (
                ("role", "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'employee'"),
                ("department", "ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(50)"),
                ("manager_id", "ALTER TABLE users ADD COLUMN IF NOT EXISTS manager_id INTEGER"),
                (
                    "department_head_for",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS department_head_for VARCHAR(50)",
                ),
            ):
                if not column_exists("users", col):
                    conn.execute(text(ddl))
                    conn.commit()
                    print(f"Added users.{col}")

        if column_exists("claims", "id"):
            if not column_exists("claims", "rejection_reason"):
                conn.execute(text("ALTER TABLE claims ADD COLUMN rejection_reason TEXT"))
                conn.commit()
            if not column_exists("claims", "is_reimbursable"):
                conn.execute(
                    text("ALTER TABLE claims ADD COLUMN is_reimbursable BOOLEAN DEFAULT TRUE")
                )
                conn.commit()

        if column_exists("claim_approvals", "id"):
            if not column_exists("claim_approvals", "sequence_order"):
                conn.execute(
                    text(
                        "ALTER TABLE claim_approvals ADD COLUMN sequence_order INTEGER DEFAULT 1"
                    )
                )
                conn.commit()

        if column_exists("expenses", "id") and not column_exists("expenses", "claim_id"):
            conn.execute(
                text("ALTER TABLE expenses ADD COLUMN claim_id INTEGER")
            )
            conn.commit()

        try:
            conn.execute(
                text("ALTER TYPE maincategory ADD VALUE IF NOT EXISTS 'policy'")
            )
            conn.commit()
        except Exception:
            conn.rollback()

    from app.models import Policy, Claim, ClaimApproval

    with engine.connect() as conn:
        # Recreate policy tables with string enums (avoids PG enum mismatch)
        for stmt in (
            "DROP TABLE IF EXISTS claim_approvals CASCADE",
            "DROP TABLE IF EXISTS claims CASCADE",
            "DROP TABLE IF EXISTS policies CASCADE",
        ):
            conn.execute(text(stmt))
            conn.commit()

    for table in (Policy.__table__, Claim.__table__, ClaimApproval.__table__):
        table.create(engine, checkfirst=True)
        print(f"Created table: {table.name}")

    print("Policy schema migration completed.")


if __name__ == "__main__":
    run()
