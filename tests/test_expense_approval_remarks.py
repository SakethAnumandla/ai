"""Expense approval remarks stored and returned in bill details."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["PADDLE_OCR_PRELOAD"] = "0"
os.environ["REDIS_ENABLED"] = "0"

import app.database as db_module
from app.database import Base, get_db
from app.dependencies import DEV_USER_USERNAME
from app.main import app
from app.models import (
    ApprovalStatus,
    Expense,
    ExpenseApproval,
    ExpenseStatus,
    MainCategory,
    TransactionType,
    UploadMethod,
    User,
    UserRole,
    Wallet,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
db_module.engine = engine
db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def _seed_submitted_expense_with_step(db) -> tuple[Expense, ExpenseApproval]:
    user = User(
        email="dev@local.test",
        username=DEV_USER_USERNAME,
        hashed_password="x",
        is_admin=True,
        role=UserRole.SUPER_ADMIN,
    )
    db.add(user)
    db.flush()
    db.add(Wallet(user_id=user.id))
    expense = Expense(
        user_id=user.id,
        bill_name="Remarks test bill",
        bill_amount=1200.0,
        bill_date=datetime.now(timezone.utc),
        transaction_type=TransactionType.EXPENSE,
        main_category=MainCategory.MISCELLANEOUS,
        upload_method=UploadMethod.MANUAL,
        status=ExpenseStatus.SUBMITTED,
    )
    db.add(expense)
    db.flush()
    step = ExpenseApproval(
        expense_id=expense.id,
        approval_level="manager",
        sequence_order=1,
        approver_id=user.id,
        approver_name="Dev User",
        approver_role_label="Manager",
        status=ApprovalStatus.PENDING,
    )
    db.add(step)
    db.commit()
    db.refresh(expense)
    db.refresh(step)
    return expense, step


@pytest.fixture()
def client():
    db = db_module.SessionLocal()
    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        expense, step = _seed_submitted_expense_with_step(db)

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            c._test_expense_id = expense.id
            c._test_approval_id = step.id
            yield c
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_approve_stores_remarks_in_bill_details(client: TestClient):
    approval_id = client._test_approval_id
    expense_id = client._test_expense_id

    r = client.post(
        f"/expenses/approvals/{approval_id}/action",
        json={"action": "approve", "remarks": "Verified receipt and amount"},
    )
    assert r.status_code == 200, r.text

    details = client.get(f"/expenses/{expense_id}/details")
    assert details.status_code == 200
    body = details.json()
    assert len(body["remarks_table"]) == 1
    row = body["remarks_table"][0]
    assert row["approval_id"] == approval_id
    assert row["action"] == "approved"
    assert row["remarks"] == "Verified receipt and amount"
    assert row["role_label"] == "Manager"
    assert body["approval_remarks"][0]["remarks"] == "Verified receipt and amount"


def test_reject_requires_remarks(client: TestClient):
    approval_id = client._test_approval_id

    r = client.post(
        f"/expenses/approvals/{approval_id}/action",
        json={"action": "reject"},
    )
    assert r.status_code == 400
    assert "remarks are required" in r.json()["detail"].lower()


def test_reject_stores_remarks(client: TestClient):
    approval_id = client._test_approval_id
    expense_id = client._test_expense_id

    r = client.post(
        f"/expenses/approvals/{approval_id}/action",
        json={"action": "reject", "comments": "Missing GST invoice"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    assert r.json()["rejection_reason"] == "Missing GST invoice"

    remarks = client.get(f"/expenses/{expense_id}/approval-remarks")
    assert remarks.status_code == 200
    payload = remarks.json()
    assert payload["count"] == 1
    assert payload["remarks_table"][0]["action"] == "rejected"
    assert payload["remarks_table"][0]["remarks"] == "Missing GST invoice"
