"""
Complete API route inventory + smoke test — every endpoint must return 2xx success.

Run:
  python3.11 -m pytest tests/test_all_api_routes.py -v
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

from tests.seed_data import MINIMAL_PNG, MINIMAL_WEBM, SeedIds

SKIP_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"})
SUCCESS_STATUS = frozenset({200, 201, 202, 204})


def _collect_routes() -> List[Tuple[str, str]]:
    from app.main import app

    seen: set[Tuple[str, str]] = set()
    routes: List[Tuple[str, str]] = []
    for route in app.routes:
        if not hasattr(route, "methods") or not hasattr(route, "path"):
            continue
        if route.path in SKIP_PATHS:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            key = (method, route.path)
            if key not in seen:
                seen.add(key)
                routes.append(key)
    routes.sort(key=lambda x: (x[1], x[0]))
    return routes


ALL_API_ROUTES: List[Tuple[str, str]] = _collect_routes()
API_ROUTE_COUNT: int = len(ALL_API_ROUTES)


def _seed() -> SeedIds:
    from tests import api_test_context

    if api_test_context.CURRENT_SEED is None:
        raise RuntimeError("Test seed not initialized — conftest seeded_database fixture missing")
    return api_test_context.CURRENT_SEED


def _resolve_path(path: str, method: str = "GET") -> str:
    s = _seed()
    expense_id = str(s.expense_draft_id)
    if path.endswith("/discard"):
        expense_id = str(s.expense_empty_draft_id)
    elif path.endswith("/resubmit"):
        expense_id = str(s.expense_rejected_id)
    elif path.endswith("/approve") or "approval-workflow" in path:
        expense_id = str(s.expense_submitted_id)
    elif "/files" in path or "/thumbnail" in path:
        expense_id = str(s.expense_thumb_id)

    expense_approval_id = str(s.expense_approval_id)
    claim_approval_id = str(s.claim_approval_id)
    approval_id = (
        expense_approval_id
        if path.startswith("/expenses/approvals/")
        else claim_approval_id
    )

    job_id = (
        str(s.finance_report_job_id)
        if "/finance/reports/" in path
        else str(s.job_id)
    )

    policy_id = (
        str(s.policy_deletable_id)
        if method == "DELETE" and path == "/policies/{policy_id}"
        else str(s.policy_id)
    )

    replacements = {
        "{expense_id}": expense_id,
        "{approval_id}": approval_id,
        "{claim_id}": str(s.claim_id),
        "{policy_id}": policy_id,
        "{bill_id}": str(s.ocr_bill_id),
        "{batch_id}": str(s.ocr_batch_id),
        "{file_id}": str(s.expense_file_id),
        "{session_id}": s.session_id,
        "{job_id}": job_id,
        "{alert_id}": str(s.alert_id),
        "{snapshot_id}": str(s.snapshot_a_id),
        "{export_id}": s.bulk_export_id,
        "{category}": "meals_entertainment",
    }
    resolved = path
    for token, value in replacements.items():
        resolved = resolved.replace(token, value)
    return resolved


def _query_params(path: str) -> Dict[str, str]:
    s = _seed()
    if path == "/budgets/monthly":
        return {"financial_year": "FY2025-26"}
    if path == "/dashboard/export-by-fy":
        return {"financial_year": "FY2025-26", "group_by": "month"}
    if path == "/dashboard/export-data":
        return {"period": "this_month", "format": "json"}
    if path == "/finance/snapshots/compare":
        return {
            "a": str(s.snapshot_a_id),
            "b": str(s.snapshot_b_id),
        }
    if path == "/finance/reports/versions":
        return {"report_type": "spend_summary"}
    if path == "/ai/chat/welcome":
        return {"session_id": s.session_id}
    return {}


def _json_body(method: str, path: str) -> Optional[Dict[str, Any]]:
    if method not in ("POST", "PUT", "PATCH"):
        return None
    s = _seed()
    now = datetime.now(timezone.utc).isoformat()

    if path == "/ai/chat":
        return {"message": "hello", "session_id": s.session_id}
    if path == "/ai/chat/end":
        return None
    if path == "/ai/memory/policy":
        return {"retention_days": 90, "max_entries": 1000}
    if path == "/expenses/approvals/{approval_id}/action":
        return {"action": "approve", "comments": "Approved in API test"}
    if path == "/approvals/{approval_id}/action":
        return {"status": "approved", "comments": "Approved in API test", "approved_amount": 500.0}
    if path == "/manager/approvals/simulate":
        return {"approval_ids": [s.claim_approval_id]}
    if path == "/manager/bulk-preview/export":
        return {"approval_ids": [s.claim_approval_id], "format": "csv"}
    if path == "/finance/snapshots/capture":
        return {
            "snapshot_type": "spend_trends",
            "period_label": "FY2025-26",
            "months": 1,
        }
    if path == "/finance/reports/async":
        return {"report_type": "spend_trends", "format": "csv", "months": 1}
    if path in ("/finance/alerts/evaluate", "/finance/cache/invalidate"):
        return {}
    if path == "/intelligence/receipt/{expense_id}/confirm-review":
        return {
            "review_token": s.review_token,
            "corrections": {
                "bill_name": "Confirmed bill",
                "bill_amount": 420.0,
            },
        }
    if path == "/expenses/{expense_id}/submit":
        return {
            "bill_name": "Draft expense",
            "bill_amount": 420.0,
            "bill_date": now,
            "main_category": "miscellaneous",
            "confirm_submit": True,
        }
    if path == "/expenses/{expense_id}/resubmit":
        return {
            "bill_name": "Resubmitted expense",
            "bill_amount": 420.0,
            "bill_date": now,
            "main_category": "miscellaneous",
            "confirm_submit": True,
        }
    if path == "/expenses/{expense_id}/approve":
        return {"status": "approved", "comments": "Legacy approve OK"}
    if path == "/expenses/{expense_id}/taxes" and method == "PUT":
        return {
            "tax_lines": [
                {
                    "tax_label": "CGST",
                    "tax_type": "cgst",
                    "calculation_type": "fixed_value",
                    "tax_amount": 10.0,
                    "recoverable": True,
                }
            ]
        }
    if path in ("/policies", "/policies/create"):
        uid = uuid.uuid4().hex[:6].upper()
        return {
            "policy_id": f"POL-TEST-{uid}",
            "policy_name": "API Test Policy",
            "policy_type": "travel",
            "maximum_amount": 5000.0,
            "main_category": "policy",
            "valid_from": now,
        }
    if path == "/policies/{policy_id}" and method == "PUT":
        return {"policy_name": "Updated policy name"}
    if path == "/expenses/{expense_id}" and method == "PATCH":
        return {"bill_name": "Updated draft name"}
    return {}


def _multipart_files(path: str) -> Optional[List[Tuple[str, Tuple[str, bytes, str]]]]:
    upload_paths = {
        "/expenses/manual/scan",
        "/expenses/upload-drafts",
        "/ocr/scan-drafts",
        "/ocr/scan",
        "/ocr/scan-batch",
        "/policies/scan-ocr",
        "/claims/scan-ocr",
        "/intelligence/receipt/scan",
        "/intelligence/receipt/scan-sync",
        "/intelligence/voice/transcribe",
        "/intelligence/voice/transcribe-sync",
        "/intelligence/voice/chat",
    }
    multi_file_paths = {
        "/expenses/upload-drafts",
        "/ocr/scan-drafts",
        "/ocr/scan-batch",
        "/expenses/{expense_id}/files",
        "/expenses/manual",
    }
    if path not in upload_paths and path not in multi_file_paths:
        return None
    payload = MINIMAL_WEBM if "voice" in path else MINIMAL_PNG
    mime = "audio/webm" if "voice" in path else "image/png"
    name = "audio.webm" if "voice" in path else "receipt.png"
    field = "files" if path in multi_file_paths else "file"
    return [(field, (name, payload, mime))]


def _form_data(method: str, path: str) -> Optional[Dict[str, str]]:
    if method != "POST":
        return None
    s = _seed()
    now = datetime.now(timezone.utc).isoformat()

    if path == "/expenses/manual":
        return {
            "bill_name": f"Manual API test {uuid.uuid4().hex[:6]}",
            "bill_amount": "99.0",
            "bill_date": "15/05/2026",
            "main_category": "miscellaneous",
            "save_as_draft": "true",
        }
    if path == "/claims/submit":
        return {
            "policy_id": str(s.policy_id),
            "bill_name": "Claim API test",
            "bill_amount": "250.0",
            "bill_date": now,
        }
    if path == "/claims/scan-ocr":
        return {"policy_id": str(s.policy_id)}
    if path == "/ai/chat/upload":
        return {
            "session_id": s.session_id,
            "message": "hello",
        }
    if path.startswith("/intelligence/voice"):
        return {"language": "en", "session_id": s.session_id}
    if path == "/intelligence/receipt/scan-sync":
        return {"force_rescan": "false"}
    return None


def _call_route(client: TestClient, method: str, path: str):
    url = _resolve_path(path, method)
    params = _query_params(path)
    files = _multipart_files(path)
    form = _form_data(method, path)
    body = _json_body(method, path)

    if path == "/ai/chat/end":
        s = _seed()
        return client.post(url, params={**params, "session_id": s.session_id})

    if files:
        data = form or {}
        if path == "/ocr/scan-batch":
            data.setdefault("batch_name", "api-test-batch")
        return client.post(url, params=params, data=data, files=files)

    if form and path == "/ai/chat/upload":
        return client.post(
            url,
            params=params,
            data=form,
            files=[("files", ("receipt.png", MINIMAL_PNG, "image/png"))],
        )

    if form:
        return client.post(url, params=params, data=form)

    if method == "GET":
        return client.get(url, params=params)
    if method == "POST":
        if body is not None:
            return client.post(url, params=params, json=body)
        return client.post(url, params=params)
    if method == "PUT":
        return client.put(url, params=params, json=body or {})
    if method == "PATCH":
        return client.patch(url, params=params, json=body or {})
    if method == "DELETE":
        return client.delete(url, params=params)
    raise ValueError(f"Unsupported method: {method}")


def test_api_route_inventory_count():
    assert API_ROUTE_COUNT >= 140


def _route_test_id(method: str, path: str) -> str:
    slug = path.strip("/").replace("/", "_").replace("{", "").replace("}", "") or "root"
    if path.endswith("/") and len(path) > 1:
        slug = f"{slug}__"
    return f"{method}_{slug}"


@pytest.mark.parametrize(
    "method,path",
    ALL_API_ROUTES,
    ids=[_route_test_id(m, p) for m, p in ALL_API_ROUTES],
)
def test_api_route_returns_success(client: TestClient, method: str, path: str):
    """Every registered route must return HTTP 2xx success."""
    response = _call_route(client, method, path)
    assert response.status_code in SUCCESS_STATUS, (
        f"{method} {path} -> {response.status_code}: {response.text[:400]}"
    )


def test_all_routes_grouped_summary():
    prefixes = {path.split("/")[1] for _, path in ALL_API_ROUTES if path != "/"}
    expected = {
        "ai", "approvals", "budgets", "categories", "claims", "dashboard",
        "executive", "expenses", "filters", "finance", "health", "intelligence",
        "manager", "ocr", "payment-modes", "policies", "policy-types", "tax", "wallet",
    }
    assert expected.issubset(prefixes)
