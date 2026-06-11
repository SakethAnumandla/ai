#!/usr/bin/env python3
"""Generate docs/API_CURL_REFERENCE.md — copy-paste curls for manual testing."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_postman_collection import (  # noqa: E402
    FOLDER_ORDER,
    SKIP_PATHS,
    SKIP_ROUTE_PREFIXES,
    _collect_routes,
    _file_upload_body,
    _folder_name,
    _form_body,
    _json_body,
    _path_to_postman,
    _query_params,
)

BASE = "http://127.0.0.1:8000"
PROD = "https://api.bizwy.in"
OUT = ROOT / "docs" / "API_CURL_REFERENCE.md"
RECEIPT = ROOT / "scripts" / "fixtures" / "receipt.png"
VOICE = ROOT / "scripts" / "fixtures" / "sample.webm"

# Default IDs — re-run bootstrap to refresh (POST /api-test/bootstrap)
DEFAULT_IDS = {
    "base_url": BASE,
    "session_id": "api-test-session01",
    "expense_draft_id": "31",
    "expense_submitted_id": "32",
    "expense_empty_draft_id": "33",
    "expense_rejected_id": "34",
    "expense_thumb_id": "35",
    "expense_file_id": "23",
    "expense_approval_id": "18",
    "policy_id": "8",
    "policy_deletable_id": "9",
    "claim_id": "4",
    "claim_approval_id": "4",
    "ocr_bill_id": "5",
    "ocr_batch_id": "4",
    "job_id": "5",
    "finance_report_job_id": "6",
    "snapshot_a_id": "8",
    "snapshot_b_id": "9",
    "alert_id": "2",
    "bulk_export_id": "0112cdbe-b393-4f93-b002-7ae2c2d0c403",
    "review_token": "api-test-review-token-0001",
    "category": "meals_entertainment",
    "financial_year": "FY2025-26",
}


def sub(text: str, ids: dict[str, str]) -> str:
    out = text
    for key, value in sorted(ids.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(f"{{{{{key}}}}}", str(value))
    return out


def resolve_path(path: str, method: str, ids: dict[str, str]) -> str:
    return sub(_path_to_postman(path, method), ids)


def resolve_query(path: str, ids: dict[str, str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in _query_params(path):
        if item.get("disabled"):
            continue
        params[item["key"]] = sub(str(item["value"]), ids)
    if path == "/ai/chat/end":
        params["session_id"] = ids["session_id"]
    return params


def build_curl(method: str, path: str, ids: dict[str, str]) -> tuple[str, str]:
    """Return (full_url, curl_command)."""
    url_path = resolve_path(path, method, ids)
    query = resolve_query(path, ids)
    base = ids.get("base_url", BASE)
    url = f"{base}{url_path}"
    if query:
        url = f"{url}?{urlencode(query)}"

    lines = [f"curl -X {method} '{url}'"]
    json_raw = sub(_json_body(method, path) or "", ids) if _json_body(method, path) else None
    form = _form_body(path) or []
    uploads = _file_upload_body(path) or []

    if json_raw and method in ("POST", "PUT", "PATCH") and not form and not uploads:
        lines[0] = f"curl -X {method} '{url}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{json_raw}'"
    elif form or uploads:
        parts = [f"curl -X {method} '{url}' \\"]
        for item in form:
            if item.get("type") == "file":
                src = ROOT / item["src"]
                if not src.is_file():
                    src = RECEIPT
                parts.append(f"  -F '{item['key']}=@{src}' \\")
            else:
                parts.append(f"  -F '{item['key']}={sub(str(item.get('value', '')), ids)}' \\")
        for item in uploads:
            src = ROOT / item["src"]
            if not src.is_file():
                src = RECEIPT if "webm" not in item.get("src", "") else VOICE
            parts.append(f"  -F '{item['key']}=@{src}' \\")
        if path == "/ocr/scan-batch":
            parts.insert(1, "  -F 'batch_name=curl-batch' \\")
        lines = ["\n".join(parts).rstrip(" \\").rstrip("\\")]
    return url, lines[0]


def main() -> int:
    routes = _collect_routes()
    # Add bootstrap (not in main route list due to skip prefix)
    bootstrap_routes = [("GET", "/api-test/bootstrap"), ("POST", "/api-test/bootstrap")]

    by_folder: dict[str, list[tuple[str, str, str, str]]] = {}
    for method, path in bootstrap_routes + routes:
        if path in SKIP_PATHS:
            continue
        if any(path.startswith(p) for p in SKIP_ROUTE_PREFIXES) and path != "/api-test/bootstrap":
            continue
        folder = "Setup (run first)" if path == "/api-test/bootstrap" else _folder_name(path)
        url, curl = build_curl(method, path, DEFAULT_IDS)
        by_folder.setdefault(folder, []).append((method, path, url, curl))

    lines = [
        "# Bizwy Expense API — Manual Test Reference",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Base URLs",
        "",
        f"| Environment | Base URL |",
        f"|-------------|----------|",
        f"| **Local** | `{BASE}` |",
        f"| **Production** | `{PROD}` |",
        "",
        "> **No auth header needed** — the API auto-uses a dev user (`devuser`) locally.",
        "",
        "## How to test",
        "",
        "### Option A — Browser (GET only)",
        "Copy any **Browser URL** below and paste into Chrome/Safari. You will see JSON output.",
        "",
        "### Option B — Terminal (all methods)",
        "Copy the **curl** block and paste in Terminal.",
        "",
        "### Option C — Postman (recommended for POST/file uploads)",
        "1. Import `postman/Bizwy_Expense_API.postman_collection.json`",
        "2. Import `postman/Bizwy_Expense_API.postman_environment.json`",
        "3. Run **Setup → POST api-test / bootstrap** first (fills all `{{ids}}`)",
        "4. Run any request — results show in Postman **Body** tab",
        "",
        "## Step 1 — Bootstrap (get live IDs)",
        "",
        "Run this **first** so path variables match your database:",
        "",
        "```bash",
        f"curl -X POST '{BASE}/api-test/bootstrap'",
        "```",
        "",
        "**Browser:**",
        f"[{BASE}/api-test/bootstrap]({BASE}/api-test/bootstrap)",
        "",
        "Copy values from `ids` in the response into the variables below if they differ:",
        "",
        "```json",
        json.dumps(DEFAULT_IDS, indent=2),
        "```",
        "",
        "---",
        "",
    ]

    order = ["Setup (run first)"] + [f for f in FOLDER_ORDER if f != "Setup (run first)"]
    seen_folders: set[str] = set()
    n = 0
    for folder in order:
        if folder not in by_folder or folder in seen_folders:
            continue
        seen_folders.add(folder)
        items = sorted(by_folder[folder], key=lambda x: (x[1], x[0]))
        lines.append(f"## {folder}")
        lines.append("")
        for method, path, url, curl in items:
            n += 1
            lines.append(f"### {n}. `{method} {path}`")
            lines.append("")
            if method == "GET":
                lines.append(f"**Browser URL:** [{url}]({url})")
                lines.append("")
            lines.append("**curl:**")
            lines.append("```bash")
            lines.append(curl)
            lines.append("```")
            lines.append("")

    for folder, items in sorted(by_folder.items()):
        if folder in seen_folders:
            continue
        lines.append(f"## {folder}")
        lines.append("")
        for method, path, url, curl in sorted(items, key=lambda x: (x[1], x[0])):
            n += 1
            lines.append(f"### {n}. `{method} {path}`")
            lines.append("")
            if method == "GET":
                lines.append(f"**Browser URL:** [{url}]({url})")
                lines.append("")
            lines.append("**curl:**")
            lines.append("```bash")
            lines.append(curl)
            lines.append("```")
            lines.append("")

    lines.extend([
        "---",
        "",
        f"**Total APIs documented:** {n}",
        "",
        f"Swagger UI (interactive): [{BASE}/docs]({BASE}/docs)",
        "",
    ])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {n} APIs -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
