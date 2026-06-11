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
from tests.seed_data import ensure_api_fixtures, reset_and_seed


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Seed API test fixtures for Postman/Newman")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe all tables first (local dev only)",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ids = reset_and_seed(db) if args.reset else ensure_api_fixtures(db)
    finally:
        db.close()

    print("API seed complete. Run POST /api-test/bootstrap or Newman Setup folder for live IDs:")
    for field, value in vars(ids).items():
        print(f"  {field}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
