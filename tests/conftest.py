"""Pytest fixtures for API integration tests (dev auth + Bizwy test users)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, Generator, Tuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

# Dev auth before app import
os.environ.setdefault("BIZWY_AUTH_MODE", "dev")

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User, UserRole  # noqa: E402

# Bizwy test accounts from product spec
USER_A: Dict[str, int] = {"user_id": 39120, "company_id": 12}
USER_B: Dict[str, int] = {"user_id": 3489, "company_id": 2}

_TEST_USERS = (
    (USER_A["user_id"], "bizwy_user_a@test.local", "bizwy39120", "Bizwy User A"),
    (USER_B["user_id"], "bizwy_user_b@test.local", "bizwy3489", "Bizwy User B"),
)


def _ensure_schema() -> None:
    from app.migrations.add_expense_company_scope import run as migrate_company_scope

    migrate_company_scope()


def _seed_bizwy_users() -> None:
    db = SessionLocal()
    try:
        for uid, email, username, full_name in _TEST_USERS:
            exists = db.query(User.id).filter(User.id == uid).first()
            if exists:
                continue
            db.add(
                User(
                    id=uid,
                    email=email,
                    username=username,
                    hashed_password="test-not-used",
                    full_name=full_name,
                    is_active=True,
                    is_admin=False,
                    role=UserRole.EMPLOYEE,
                )
            )
        db.commit()
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('users', 'id'), "
                "GREATEST((SELECT COALESCE(MAX(id), 1) FROM users), 1))"
            )
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def _prepare_database() -> None:
    _ensure_schema()
    _seed_bizwy_users()


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def scope_params(scope: Dict[str, int]) -> Dict[str, int]:
    return {"user_id": scope["user_id"], "company_id": scope["company_id"]}


@pytest.fixture()
def user_a() -> Dict[str, int]:
    return dict(USER_A)


@pytest.fixture()
def user_b() -> Dict[str, int]:
    return dict(USER_B)
