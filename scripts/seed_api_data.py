"""
Seed PostgreSQL with full API test data for Postman / manual smoke tests.

Run against local Docker Postgres:
  DATABASE_URL=postgresql://user:password@localhost:5432/expense_tracker \\
    python scripts/seed_api_data.py

Or inside the backend container (uses container DATABASE_URL):
  docker exec bizwy_expense_backend_new-main-backend-1 python scripts/seed_api_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app.database import Base, SessionLocal, engine
import app.ai.models as _ai  # noqa: F401
import app.finance.models as _finance  # noqa: F401
from tests.seed_data import reset_and_seed


def main() -> int:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ids = reset_and_seed(db)
    finally:
        db.close()

    print("API seed complete. Use these IDs in Postman path/query params:")
    for field, value in vars(ids).items():
        print(f"  {field}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
