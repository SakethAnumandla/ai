"""Generate Postman Collection v2.1 for all Bizwy Expense API routes."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT_DIR = ROOT / "postman"
COLLECTION_PATH = OUT_DIR / "Bizwy_Expense_API.postman_collection.json"
ENV_PATH = OUT_DIR / "Bizwy_Expense_API.postman_environment.json"

SKIP_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"})

DEFAULT_BASE_URL = "http://localhost:8000"

# Collection variables — run `python scripts/seed_api_data.py` and paste printed IDs here.
COLLECTION_VARS = [
    ("base_url", DEFAULT_BASE_URL),
    ("session_id", "api-test-session01"),
    ("expense_draft_id", "1"),
    ("expense_submitted_id", "2"),
    ("expense_empty_draft_id", "3"),
    ("expense_rejected_id", "4"),
    ("expense_thumb_id", "5"),
    ("expense_file_id", "1"),
    ("expense_approval_id", "1"),
    ("policy_id", "1"),
    ("policy_deletable_id", "2"),
    ("claim_id", "1"),
    ("claim_approval_id", "1"),
    ("ocr_bill_id", "1"),
    ("ocr_batch_id", "1"),
    ("job_id", "1"),
    ("finance_report_job_id", "2"),
    ("snapshot_a_id", "1"),
    ("snapshot_b_id", "2"),
    ("alert_id", "1"),
    ("bulk_export_id", "00000000-0000-0000-0000-000000000001"),
    ("review_token", "api-test-review-token-0001"),
    ("category", "meals_entertainment"),
    ("financial_year", "FY2025-26"),
]

FOLDER_ORDER = [
    "General",
    "Health",
    "Categories & Tax",
    "Filters",
    "Expenses",
    "Expense Workflow",
    "OCR",
    "Wallet",
    "Dashboard",
    "Policies",
    "Claims",
    "Approvals",
    "AI Chat",
    "AI Memory",
    "Intelligence",
    "Manager",
    "Finance",
    "Executive",
]


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


def _folder_name(path: str) -> str:
    if path in ("/", "/health"):
        return "Health" if path == "/health" else "General"
    segment = path.strip("/").split("/")[0]
    mapping = {
        "categories": "Categories & Tax",
        "tax": "Categories & Tax",
        "payment-modes": "Categories & Tax",
        "policy-types": "Categories & Tax",
        "filters": "Filters",
        "expenses": "Expenses",
        "budgets": "Expense Workflow",
        "ocr": "OCR",
        "wallet": "Wallet",
        "dashboard": "Dashboard",
        "policies": "Policies",
        "claims": "Claims",
        "approvals": "Approvals",
        "ai": "AI Chat",
        "intelligence": "Intelligence",
        "manager": "Manager",
        "finance": "Finance",
        "executive": "Executive",
    }
    return mapping.get(segment, segment.title())


def _path_to_postman(path: str, method: str) -> str:
    """Map FastAPI path params to Postman {{variables}}."""
    expense_id = "{{expense_draft_id}}"
    if path.endswith("/discard"):
        expense_id = "{{expense_empty_draft_id}}"
    elif path.endswith("/resubmit"):
        expense_id = "{{expense_rejected_id}}"
    elif path.endswith("/approve") or "approval-workflow" in path:
        expense_id = "{{expense_submitted_id}}"
    elif "/files" in path or "/thumbnail" in path:
        expense_id = "{{expense_thumb_id}}"

    approval_id = (
        "{{expense_approval_id}}"
        if path.startswith("/expenses/approvals/")
        else "{{claim_approval_id}}"
    )
    job_id = (
        "{{finance_report_job_id}}"
        if "/finance/reports/" in path
        else "{{job_id}}"
    )
    policy_id = (
        "{{policy_deletable_id}}"
        if method == "DELETE" and path == "/policies/{policy_id}"
        else "{{policy_id}}"
    )

    replacements = {
        "{expense_id}": expense_id,
        "{approval_id}": approval_id,
        "{claim_id}": "{{claim_id}}",
        "{policy_id}": policy_id,
        "{bill_id}": "{{ocr_bill_id}}",
        "{batch_id}": "{{ocr_batch_id}}",
        "{file_id}": "{{expense_file_id}}",
        "{session_id}": "{{session_id}}",
        "{job_id}": job_id,
        "{alert_id}": "{{alert_id}}",
        "{snapshot_id}": "{{snapshot_a_id}}",
        "{export_id}": "{{bulk_export_id}}",
        "{category}": "{{category}}",
    }
    out = path
    for token, value in replacements.items():
        out = out.replace(token, value)
    return out


def _query_params(path: str) -> List[Dict[str, Any]]:
    params: List[Dict[str, Any]] = []
    if path == "/budgets/monthly":
        params.append({"key": "financial_year", "value": "{{financial_year}}"})
    elif path == "/dashboard/export-by-fy":
        params.extend(
            [
                {"key": "financial_year", "value": "{{financial_year}}"},
                {"key": "group_by", "value": "month"},
            ]
        )
    elif path == "/dashboard/export-data":
        params.extend(
            [
                {"key": "period", "value": "this_month"},
                {"key": "format", "value": "json"},
            ]
        )
    elif path == "/finance/snapshots/compare":
        params.extend(
            [
                {"key": "a", "value": "{{snapshot_a_id}}"},
                {"key": "b", "value": "{{snapshot_b_id}}"},
            ]
        )
    elif path == "/finance/reports/versions":
        params.append({"key": "report_type", "value": "spend_summary"})
    elif path == "/ai/chat/welcome":
        params.append({"key": "session_id", "value": "{{session_id}}"})
    elif path == "/wallet/summary":
        params.append({"key": "time_period", "value": "all_time"})
    elif path == "/wallet/transactions":
        params.extend(
            [
                {"key": "time_period", "value": "all_time"},
                {"key": "limit", "value": "20"},
            ]
        )
    elif path == "/expenses":
        params.append({"key": "status", "value": "draft", "disabled": True})
    return params


def _json_body(method: str, path: str) -> Optional[str]:
    if method not in ("POST", "PUT", "PATCH"):
        return None
    now = datetime.now(timezone.utc).isoformat()

    bodies: Dict[str, Any] = {
        "/ai/chat": {"message": "hello", "session_id": "{{session_id}}"},
        "/ai/memory/policy": {"retention_days": 90, "max_entries": 1000},
        "/expenses/approvals/{approval_id}/action": {
            "action": "approve",
            "comments": "Approved in Postman",
        },
        "/approvals/{approval_id}/action": {
            "status": "approved",
            "comments": "Approved in Postman",
            "approved_amount": 500.0,
        },
        "/manager/approvals/simulate": {"approval_ids": ["{{claim_approval_id}}"]},
        "/manager/bulk-preview/export": {
            "approval_ids": ["{{claim_approval_id}}"],
            "format": "csv",
        },
        "/finance/snapshots/capture": {
            "snapshot_type": "spend_trends",
            "period_label": "{{financial_year}}",
            "months": 1,
        },
        "/finance/reports/async": {
            "report_type": "spend_trends",
            "format": "csv",
            "months": 1,
        },
        "/finance/alerts/evaluate": {},
        "/finance/cache/invalidate": {},
        "/intelligence/receipt/{expense_id}/confirm-review": {
            "review_token": "{{review_token}}",
            "corrections": {"bill_name": "Confirmed bill", "bill_amount": 420.0},
        },
        "/expenses/{expense_id}/submit": {
            "bill_name": "Draft expense",
            "bill_amount": 420.0,
            "bill_date": now,
            "main_category": "miscellaneous",
            "confirm_submit": True,
        },
        "/expenses/{expense_id}/resubmit": {
            "bill_name": "Resubmitted expense",
            "bill_amount": 420.0,
            "bill_date": now,
            "main_category": "miscellaneous",
            "confirm_submit": True,
        },
        "/expenses/{expense_id}/approve": {
            "status": "approved",
            "comments": "Legacy approve OK",
        },
        "/policies": {
            "policy_id": "POL-POSTMAN-001",
            "policy_name": "Postman Test Policy",
            "policy_type": "travel",
            "maximum_amount": 5000.0,
            "main_category": "policy",
            "valid_from": now,
        },
        "/policies/create": {
            "policy_id": "POL-POSTMAN-002",
            "policy_name": "Postman Test Policy 2",
            "policy_type": "travel",
            "maximum_amount": 5000.0,
            "main_category": "policy",
            "valid_from": now,
        },
        "/policies/{policy_id}": {"policy_name": "Updated policy name"},
        "/expenses/{expense_id}": {"bill_name": "Updated draft name"},
    }
    if path == "/expenses/{expense_id}/taxes" and method == "PUT":
        bodies[path] = {
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
    if path not in bodies:
        if method in ("POST", "PUT", "PATCH"):
            return "{}"
        return None
    return json.dumps(bodies[path], indent=2)


def _form_body(path: str) -> Optional[List[Dict[str, Any]]]:
    now = datetime.now(timezone.utc).isoformat()
    if path == "/expenses/manual":
        return [
            {"key": "bill_name", "value": "Manual Postman test", "type": "text"},
            {"key": "bill_amount", "value": "99.0", "type": "text"},
            {"key": "bill_date", "value": "15/05/2026", "type": "text"},
            {"key": "main_category", "value": "miscellaneous", "type": "text"},
            {"key": "save_as_draft", "value": "true", "type": "text"},
            {
                "key": "files",
                "type": "file",
                "src": "scripts/fixtures/bhagini_receipt.png",
                "description": "Attach receipt image",
            },
        ]
    if path == "/claims/submit":
        return [
            {"key": "policy_id", "value": "{{policy_id}}", "type": "text"},
            {"key": "bill_name", "value": "Claim Postman test", "type": "text"},
            {"key": "bill_amount", "value": "250.0", "type": "text"},
            {"key": "bill_date", "value": now, "type": "text"},
        ]
    if path == "/claims/scan-ocr":
        return [
            {"key": "policy_id", "value": "{{policy_id}}", "type": "text"},
            {
                "key": "file",
                "type": "file",
                "src": "scripts/fixtures/bhagini_receipt.png",
            },
        ]
    if path == "/ai/chat/upload":
        return [
            {"key": "session_id", "value": "{{session_id}}", "type": "text"},
            {"key": "message", "value": "Review this receipt", "type": "text"},
            {
                "key": "files",
                "type": "file",
                "src": "scripts/fixtures/bhagini_receipt.png",
            },
        ]
    if path.startswith("/intelligence/voice"):
        return [
            {"key": "language", "value": "en", "type": "text"},
            {"key": "session_id", "value": "{{session_id}}", "type": "text"},
            {
                "key": "file",
                "type": "file",
                "src": [],
                "description": "Upload audio/webm from mic",
            },
        ]
    if path == "/intelligence/receipt/scan-sync":
        return [
            {"key": "force_rescan", "value": "false", "type": "text"},
            {
                "key": "file",
                "type": "file",
                "src": "scripts/fixtures/bhagini_receipt.png",
            },
        ]
    return None


def _file_upload_body(path: str) -> Optional[List[Dict[str, Any]]]:
    receipt = "scripts/fixtures/bhagini_receipt.png"
    multi = {
        "/expenses/upload-drafts",
        "/ocr/scan-drafts",
        "/ocr/scan-batch",
        "/expenses/{expense_id}/files",
    }
    if path in multi:
        return [
            {
                "key": "files",
                "type": "file",
                "src": receipt,
                "description": "Receipt image(s)",
            }
        ]
    if path == "/ocr/scan-batch":
        return [
            {"key": "batch_name", "value": "postman-batch", "type": "text"},
            {"key": "files", "type": "file", "src": receipt},
        ]
    uploads = {
        "/expenses/manual/scan": "file",
        "/ocr/scan": "file",
        "/policies/scan-ocr": "file",
        "/intelligence/receipt/scan": "file",
    }
    if path in uploads:
        return [{"key": uploads[path], "type": "file", "src": receipt}]
    if path == "/ocr/scan":
        return [
            {"key": "file", "type": "file", "src": receipt},
        ]
    return None


def _request_name(method: str, path: str) -> str:
    slug = path.strip("/").replace("/", " / ").replace("{", "").replace("}", "")
    if not slug:
        slug = "root"
    return f"{method} {slug}"


def _build_request(method: str, path: str) -> Dict[str, Any]:
    url_path = _path_to_postman(path, method)
    query = _query_params(path)
    request: Dict[str, Any] = {
        "method": method,
        "header": [],
        "url": {
            "raw": "{{base_url}}" + url_path,
            "host": ["{{base_url}}"],
            "path": [p for p in url_path.strip("/").split("/") if p],
        },
    }
    if query:
        request["url"]["query"] = query

    if path == "/ai/chat/end":
        request["url"]["query"] = [{"key": "session_id", "value": "{{session_id}}"}]

    form = _form_body(path)
    files = _file_upload_body(path)
    raw_json = _json_body(method, path)

    if form:
        request["body"] = {"mode": "formdata", "formdata": form}
    elif files and method == "POST":
        extra = []
        if path == "/ocr/scan-batch":
            extra = [{"key": "batch_name", "value": "postman-batch", "type": "text"}]
        request["body"] = {"mode": "formdata", "formdata": extra + files}
    elif raw_json is not None and method in ("POST", "PUT", "PATCH"):
        request["header"].append({"key": "Content-Type", "value": "application/json"})
        request["body"] = {
            "mode": "raw",
            "raw": raw_json,
            "options": {"raw": {"language": "json"}},
        }

    return request


def _build_collection(
    routes: List[Tuple[str, str]],
    *,
    base_url: str,
    env_name: str,
) -> Dict[str, Any]:
    folders: Dict[str, List[Dict[str, Any]]] = {}
    for method, path in routes:
        folder = _folder_name(path)
        folders.setdefault(folder, []).append(
            {
                "name": _request_name(method, path),
                "request": _build_request(method, path),
                "response": [],
            }
        )

    items = []
    ordered = FOLDER_ORDER + sorted(set(folders) - set(FOLDER_ORDER))
    for name in ordered:
        if name not in folders:
            continue
        items.append({"name": name, "item": folders[name]})

    collection_vars = [(k, base_url if k == "base_url" else v) for k, v in COLLECTION_VARS]

    return {
        "info": {
            "_postman_id": str(uuid.uuid4()),
            "name": "Bizwy Expense API",
            "description": (
                "Complete Postman collection for Bizwy Expense Backend.\n\n"
                f"**Base URL:** `{base_url}`\n"
                f"**Environment:** {env_name}\n\n"
                "**Setup:**\n"
                "1. Import this collection and the environment file into Postman.\n"
                "2. Select the environment from the top-right dropdown.\n"
                "3. Run **GET /health** to confirm the API is reachable.\n"
                "4. No auth required — dev user is auto-used on this backend.\n\n"
                "**Note:** OCR/upload requests reference `scripts/fixtures/bhagini_receipt.png` "
                "when testing file uploads locally."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [{"key": k, "value": v, "type": "string"} for k, v in collection_vars],
        "item": items,
    }


def _build_environment(*, base_url: str, env_name: str) -> Dict[str, Any]:
    collection_vars = [(k, base_url if k == "base_url" else v) for k, v in COLLECTION_VARS]
    return {
        "id": str(uuid.uuid4()),
        "name": env_name,
        "values": [
            {"key": k, "value": v, "type": "default", "enabled": True}
            for k, v in collection_vars
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_at": datetime.now(timezone.utc).isoformat(),
        "_postman_exported_using": "scripts/generate_postman_collection.py",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Postman collection and environment JSON.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="API base URL (no trailing slash), e.g. https://backend-new-1-z0zd.onrender.com",
    )
    parser.add_argument(
        "--env-name",
        default="Bizwy Expense API (Local)",
        help="Postman environment display name",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    base_url = args.base_url.rstrip("/")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    routes = _collect_routes()
    collection = _build_collection(routes, base_url=base_url, env_name=args.env_name)
    env = _build_environment(base_url=base_url, env_name=args.env_name)

    COLLECTION_PATH.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    ENV_PATH.write_text(json.dumps(env, indent=2), encoding="utf-8")

    print(f"Base URL: {base_url}")
    print(f"Routes: {len(routes)}")
    print(f"Collection: {COLLECTION_PATH}")
    print(f"Environment: {ENV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
