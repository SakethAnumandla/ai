"""Report HTTP status codes for all application routes (local TestClient)."""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["PADDLE_OCR_PRELOAD"] = "0"
os.environ["REDIS_ENABLED"] = "0"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.dependencies import DEV_USER_USERNAME
from app.main import app
from app.models import (
    Expense,
    ExpenseStatus,
    MainCategory,
    TransactionType,
    UploadMethod,
    User,
    UserRole,
    Wallet,
)
import app.ai.models as _ai  # noqa: F401
import app.finance.models as _finance  # noqa: F401
import app.database as db_module

import importlib.util

spec = importlib.util.spec_from_file_location(
    "test_all_api_routes", ROOT / "tests" / "test_all_api_routes.py"
)
tar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tar)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
db_module.engine = engine
db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

db = db_module.SessionLocal()
user = User(
    email="dev@local.test",
    username=DEV_USER_USERNAME,
    hashed_password="x",
    is_admin=True,
    role=UserRole.SUPER_ADMIN,
)
db.add(user)
db.flush()
db.add(Wallet(user_id=user.id, balance=10000.0))
db.add(
    Expense(
        user_id=user.id,
        bill_name="API test",
        bill_amount=42.0,
        bill_date=datetime(2026, 5, 15),
        transaction_type=TransactionType.EXPENSE,
        main_category=MainCategory.MISCELLANEOUS,
        upload_method=UploadMethod.MANUAL,
        status=ExpenseStatus.DRAFT,
    )
)
db.commit()
db.close()


def override_get_db():
    db = db_module.SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

by_status: Counter[int] = Counter()
non_2xx: list[tuple[str, str, int]] = []

with TestClient(app, raise_server_exceptions=False) as client:
    for method, path in tar.ALL_API_ROUTES:
        r = tar._call_route(client, method, path)
        by_status[r.status_code] += 1
        if r.status_code not in (200, 201, 202, 204):
            non_2xx.append((method, path, r.status_code))

twoxx = sum(v for k, v in by_status.items() if 200 <= k < 300)
total = len(tar.ALL_API_ROUTES)

print(f"Routes tested: {total}")
print(f"2xx success:   {twoxx} ({100*twoxx/total:.0f}%)")
print(f"Non-2xx:       {len(non_2xx)} ({100*len(non_2xx)/total:.0f}%)")
print(f"Breakdown:     {dict(sorted(by_status.items()))}")
print()
grouped: dict[int, list[str]] = defaultdict(list)
for m, p, c in non_2xx:
    grouped[c].append(f"{m} {p}")
for code in sorted(grouped):
    print(f"--- HTTP {code} ({len(grouped[code])}) ---")
    for line in grouped[code]:
        print(f"  {line}")
