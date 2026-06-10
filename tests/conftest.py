"""Shared pytest fixtures — in-memory SQLite with full seed per test."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["PADDLE_OCR_PRELOAD"] = "0"
os.environ["REDIS_ENABLED"] = "0"
os.environ["TESTING"] = "1"
os.environ["OCR_TEST_BYPASS"] = "1"
os.environ["OPENAI_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db


def _register_all_models() -> None:
    import app.ai.models as _ai_models  # noqa: F401
    import app.finance.models as _finance_models  # noqa: F401
    from app.models import AIChatSession  # noqa: F401


@pytest.fixture(scope="session")
def test_engine():
    _register_all_models()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.database as db_module

    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(test_engine):
    import app.database as db_module

    db = db_module.SessionLocal()
    try:
        yield db
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


@pytest.fixture(autouse=True)
def seeded_database(db_session, request):
    """Fresh full seed before each test in test_all_api_routes."""
    if "test_all_api_routes" not in getattr(request.node, "module", object()).__name__:
        yield None
        return
    from tests import api_test_context
    from tests.seed_data import reset_and_seed

    seed_ids = reset_and_seed(db_session)
    api_test_context.CURRENT_SEED = seed_ids
    yield seed_ids
    api_test_context.CURRENT_SEED = None


@pytest.fixture
def client(test_engine):
    from app.main import app

    import app.database as db_module

    def override_get_db():
        db = db_module.SessionLocal()
        try:
            yield db
        finally:
            try:
                db.rollback()
            except Exception:
                pass
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
