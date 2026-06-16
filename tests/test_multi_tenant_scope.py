"""
Integration tests: multi-tenant scope (company_id + user_id) across REST and AI APIs.

Run:  pytest tests/test_multi_tenant_scope.py -v
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.models.entities import AIConversation
from app.models import Expense, ExpenseStatus, MainCategory, TransactionType, UploadMethod
from app.schemas import ExpenseCreate
from app.services.expense_service import ExpenseService
from tests.conftest import USER_A, USER_B, scope_params


# ── Public / health ──────────────────────────────────────────────────────────


class TestPublicEndpoints:
    def test_root(self, client: TestClient):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json().get("status") == "running"

    def test_health(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["database"]["ok"] is True

    def test_categories(self, client: TestClient):
        r = client.get("/categories")
        assert r.status_code == 200

    def test_payment_modes(self, client: TestClient):
        r = client.get("/payment-modes")
        assert r.status_code == 200
        assert "payment_modes" in r.json()


# ── Scope required ───────────────────────────────────────────────────────────


class TestScopeRequired:
    @pytest.mark.parametrize(
        "path",
        [
            "/expenses",
            "/expenses/drafts",
            "/wallet/balance",
            "/wallet/transactions",
            "/dashboard/stats",
            "/dashboard/overview",
            "/ocr/bills",
            "/ai/chat/sessions",
            "/ai/chat/categories",
            "/ai/dead-letter",
        ],
    )
    def test_missing_scope_returns_400(self, client: TestClient, path: str):
        r = client.get(path)
        assert r.status_code == 400
        assert "user_id" in r.json().get("detail", "").lower()


# ── Scoped read APIs ─────────────────────────────────────────────────────────


class TestScopedReadApis:
    @pytest.mark.parametrize(
        "path",
        [
            "/expenses",
            "/expenses/drafts",
            "/wallet/balance",
            "/wallet/transactions",
            "/wallet/summary",
            "/wallet/budget-utilisation",
            "/dashboard/stats",
            "/dashboard/overview",
            "/dashboard/recent-transactions",
            "/dashboard/category-breakdown",
            "/dashboard/monthly-trend",
            "/dashboard/pending-approvals-summary",
            "/ocr/bills",
            "/ai/chat/sessions",
            "/ai/chat/categories",
            "/ai/dead-letter",
        ],
    )
    def test_user_a_endpoints_ok(self, client: TestClient, path: str):
        r = client.get(path, params=scope_params(USER_A))
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"

    @pytest.mark.parametrize(
        "path",
        [
            "/expenses",
            "/wallet/balance",
            "/dashboard/stats",
            "/ai/chat/sessions",
        ],
    )
    def test_user_b_endpoints_ok(self, client: TestClient, path: str):
        r = client.get(path, params=scope_params(USER_B))
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:300]}"


# ── Expense isolation ────────────────────────────────────────────────────────


@pytest.fixture()
def expense_for_user_a(db: Session) -> int:
    svc = ExpenseService(db)
    expense = svc.create_expense(
        db,
        ExpenseCreate(
            bill_name="Scope test expense A",
            bill_amount=250.0,
            bill_date=datetime.now(timezone.utc),
            transaction_type=TransactionType.EXPENSE,
            main_category=MainCategory.FOOD,
            vendor_name="Test Vendor A",
        ),
        user_id=USER_A["user_id"],
        upload_method=UploadMethod.MANUAL,
        status=ExpenseStatus.DRAFT,
        company_id=USER_A["company_id"],
    )
    db.commit()
    eid = expense.id
    yield eid
    db.query(Expense).filter(Expense.id == eid).delete()
    db.commit()


class TestExpenseIsolation:
    def test_owner_can_read_expense(
        self, client: TestClient, expense_for_user_a: int
    ):
        r = client.get(
            f"/expenses/{expense_for_user_a}",
            params=scope_params(USER_A),
        )
        assert r.status_code == 200
        assert r.json()["id"] == expense_for_user_a

    def test_other_user_same_company_cannot_read(
        self, client: TestClient, expense_for_user_a: int
    ):
        """Different user_id must not see the expense even with a guessed id."""
        r = client.get(
            f"/expenses/{expense_for_user_a}",
            params=scope_params(USER_B),
        )
        assert r.status_code == 404

    def test_list_only_shows_own_expenses(
        self, client: TestClient, expense_for_user_a: int
    ):
        r_a = client.get("/expenses", params=scope_params(USER_A))
        r_b = client.get("/expenses", params=scope_params(USER_B))
        assert r_a.status_code == 200
        assert r_b.status_code == 200
        ids_a = {e["id"] for e in r_a.json()}
        ids_b = {e["id"] for e in r_b.json()}
        assert expense_for_user_a in ids_a
        assert expense_for_user_a not in ids_b


# ── Wallet per company + user ───────────────────────────────────────────────


class TestWalletScope:
    def test_wallet_created_per_owner(self, client: TestClient):
        r_a = client.get("/wallet/balance", params=scope_params(USER_A))
        r_b = client.get("/wallet/balance", params=scope_params(USER_B))
        assert r_a.status_code == 200
        assert r_b.status_code == 200
        assert r_a.json()["user_id"] == USER_A["user_id"]
        assert r_b.json()["user_id"] == USER_B["user_id"]
        assert r_a.json()["id"] != r_b.json()["id"]


# ── AI chat session isolation ───────────────────────────────────────────────


class TestChatSessionIsolation:
    SESSION_ID = "scope-test-session-01"

    @pytest.fixture(autouse=True)
    def _seed_user_a_message(self, db: Session):
        row = (
            db.query(AIConversation)
            .filter(
                AIConversation.session_id == self.SESSION_ID,
                AIConversation.user_id == USER_A["user_id"],
                AIConversation.tenant_id == USER_A["company_id"],
            )
            .first()
        )
        if not row:
            db.add(
                AIConversation(
                    tenant_id=USER_A["company_id"],
                    user_id=USER_A["user_id"],
                    session_id=self.SESSION_ID,
                    role="user",
                    content="hello from user A",
                )
            )
            db.commit()
        yield
        db.query(AIConversation).filter(
            AIConversation.session_id == self.SESSION_ID
        ).delete()
        db.commit()

    def test_owner_can_list_session_messages(self, client: TestClient):
        r = client.get(
            f"/ai/chat/sessions/{self.SESSION_ID}/messages",
            params=scope_params(USER_A),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["company_id"] == USER_A["company_id"]
        assert body["user_id"] == USER_A["user_id"]
        assert len(body["messages"]) >= 1

    def test_other_user_cannot_access_session(self, client: TestClient):
        r = client.get(
            f"/ai/chat/sessions/{self.SESSION_ID}/messages",
            params=scope_params(USER_B),
        )
        assert r.status_code == 403

    def test_sessions_list_scoped(self, client: TestClient):
        r_a = client.get("/ai/chat/sessions", params=scope_params(USER_A))
        r_b = client.get("/ai/chat/sessions", params=scope_params(USER_B))
        assert r_a.status_code == 200
        assert r_b.status_code == 200
        ids_a = {s["session_id"] for s in r_a.json()["sessions"]}
        ids_b = {s["session_id"] for s in r_b.json()["sessions"]}
        assert self.SESSION_ID in ids_a
        assert self.SESSION_ID not in ids_b


# ── Manual expense API (with minimal file) ───────────────────────────────────


class TestManualExpenseApi:
    def test_manual_expense_without_file_creates_draft(self, client: TestClient, db: Session):
        r = client.post(
            "/expenses/manual",
            params=scope_params(USER_A),
            data={
                "bill_name": "Lunch no file",
                "bill_amount": "100",
                "bill_date": "2026-06-16",
                "main_category": "food",
                "save_as_draft": "true",
            },
        )
        assert r.status_code == 201, r.text[:500]
        body = r.json()
        eid = body["id"]
        try:
            assert body["bill_name"] == "Lunch no file"
            assert body["status"] == "draft"
        finally:
            db.query(Expense).filter(Expense.id == eid).delete()
            db.commit()

    def test_manual_expense_with_file_creates_draft(self, client: TestClient, db: Session):
        png = io.BytesIO(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        r = client.post(
            "/expenses/manual",
            params=scope_params(USER_A),
            data={
                "bill_name": "API test lunch",
                "bill_amount": "150",
                "bill_date": "2026-06-16",
                "main_category": "food",
                "vendor_name": "Test Cafe",
                "save_as_draft": "true",
            },
            files={"files": ("receipt.png", png, "image/png")},
        )
        assert r.status_code == 201, r.text[:500]
        body = r.json()
        eid = body["id"]
        try:
            assert body["bill_name"] == "API test lunch"
            detail = client.get(
                f"/expenses/{eid}", params=scope_params(USER_B)
            )
            assert detail.status_code == 404
        finally:
            db.query(Expense).filter(Expense.id == eid).delete()
            db.commit()
