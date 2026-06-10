"""Generate docs/API_REFERENCE.md with curl examples and live example responses.

Uses in-memory SQLite + full seed (same as API route tests).

  python scripts/generate_api_docs.py
  python scripts/generate_api_docs.py --base-url https://backend-new-1-z0zd.onrender.com
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["PADDLE_OCR_PRELOAD"] = "0"
os.environ["REDIS_ENABLED"] = "0"
os.environ["TESTING"] = "1"
os.environ["OCR_TEST_BYPASS"] = "1"
os.environ["OPENAI_API_KEY"] = "docs-generation-placeholder"
os.environ["UPLOAD_DIR"] = "/tmp/bizwy-api-docs-uploads"

OUT_PATH = ROOT / "docs" / "API_REFERENCE.md"
RECEIPT_FIXTURE = "scripts/fixtures/bhagini_receipt.png"

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from tests import api_test_context  # noqa: E402
from tests.seed_data import reset_and_seed  # noqa: E402
from tests.test_all_api_routes import (  # noqa: E402
    ALL_API_ROUTES,
    API_ROUTE_COUNT,
    _call_route,
    _form_data,
    _json_body,
    _multipart_files,
    _query_params,
    _resolve_path,
)

# Re-use folder mapping from Postman generator
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


def _register_models() -> None:
    import app.ai.models as _ai  # noqa: F401
    import app.finance.models as _finance  # noqa: F401
    from app.models import AIChatSession  # noqa: F401


def _setup_client() -> TestClient:
    Path(os.environ["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    _register_models()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.database as db_module

    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = db_module.SessionLocal()
    try:
        seed_ids = reset_and_seed(db)
    finally:
        db.close()
    api_test_context.CURRENT_SEED = seed_ids

    from app.main import app

    def override_get_db():
        db = db_module.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _build_url(base_url: str, path: str, method: str, params: Dict[str, str]) -> str:
    resolved = _resolve_path(path, method)
    url = base_url.rstrip("/") + resolved
    if params:
        url += "?" + urlencode(params)
    return url


def _build_curl(
    base_url: str,
    method: str,
    path: str,
) -> str:
    params = _query_params(path)
    url = _build_url(base_url, path, method, params)
    lines = [f'curl -s -X {method} {_shell_quote(url)}']

    if path == "/ai/chat/end":
        from tests.test_all_api_routes import _seed

        s = _seed()
        end_url = base_url.rstrip("/") + _resolve_path(path, method)
        end_url += "?" + urlencode({"session_id": s.session_id})
        lines = [f'curl -s -X POST {_shell_quote(end_url)}']

    body = _json_body(method, path)
    form = _form_data(method, path)
    files = _multipart_files(path)

    if files and method == "POST":
        for field, (name, _payload, _mime) in files:
            if field == "files":
                lines.append(f'  -F "files=@{RECEIPT_FIXTURE}"')
            else:
                lines.append(f'  -F "file=@{RECEIPT_FIXTURE}"')
        if form:
            for key, value in form.items():
                lines.append(f"  -F {_shell_quote(f'{key}={value}')}")
        if path == "/ocr/scan-batch":
            lines.append('  -F "batch_name=api-test-batch"')
    elif form and method == "POST":
        for key, value in form.items():
            lines.append(f"  -F {_shell_quote(f'{key}={value}')}")
        if path == "/ai/chat/upload":
            lines.append(f'  -F "files=@{RECEIPT_FIXTURE}"')
    elif body is not None and method in ("POST", "PUT", "PATCH"):
        payload = json.dumps(body, indent=2)
        lines.append('  -H "Content-Type: application/json"')
        lines.append(f"  -d {_shell_quote(payload)}")

    if len(lines) == 1:
        return lines[0]
    return " \\\n".join(lines)


def _format_input(method: str, path: str) -> str:
    parts: List[str] = []
    params = _query_params(path)
    if params:
        parts.append("**Query parameters**\n```json\n" + json.dumps(params, indent=2) + "\n```")

    body = _json_body(method, path)
    if body is not None and method in ("POST", "PUT", "PATCH"):
        parts.append("**JSON body**\n```json\n" + json.dumps(body, indent=2) + "\n```")

    form = _form_data(method, path)
    files = _multipart_files(path)
    if form or files:
        form_doc: Dict[str, Any] = dict(form or {})
        if files:
            form_doc["_files"] = [f"@{RECEIPT_FIXTURE}"] * len(files)
        parts.append("**Form data**\n```json\n" + json.dumps(form_doc, indent=2) + "\n```")

    if not parts:
        return "_No request body._\n"
    return "\n".join(parts) + "\n"


def _truncate_response(text: str, content_type: str, max_len: int = 4000) -> str:
    if not text:
        return "_(empty body)_"
    if "application/json" in content_type or text.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(text)
            text = json.dumps(data, indent=2, default=str)
        except json.JSONDecodeError:
            pass
    if len(text) > max_len:
        return text[:max_len] + "\n... [truncated]"
    return text


def _format_output(response) -> Tuple[str, str]:
    status = response.status_code
    content_type = response.headers.get("content-type", "")
    if status == 204:
        return str(status), "_(no content)_"
    body = _truncate_response(response.text, content_type)
    lang = "json" if "json" in content_type or body.lstrip().startswith(("{", "[")) else "text"
    return str(status), f"```{lang}\n{body}\n```"


def _anchor(method: str, path: str) -> str:
    slug = f"{method.lower()}-{path.strip('/').replace('/', '-').replace('{', '').replace('}', '')}" or "root"
    return slug.lower()


def generate_markdown(base_url: str) -> str:
    client = _setup_client()
    seed = api_test_context.CURRENT_SEED
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    folders: Dict[str, List[Tuple[str, str]]] = {}
    for method, path in ALL_API_ROUTES:
        folders.setdefault(_folder_name(path), []).append((method, path))

    lines: List[str] = [
        "# Bizwy Expense API Reference",
        "",
        f"> Auto-generated by `scripts/generate_api_docs.py` on {now}.",
        f"> **{API_ROUTE_COUNT}** endpoints documented.",
        "",
        "## Base URL",
        "",
        f"```\n{base_url.rstrip('/')}\n```",
        "",
        "## Authentication",
        "",
        "No login required for dev/Render — the backend auto-uses the `devuser` account.",
        "",
        "## Seed IDs (used in path examples below)",
        "",
        "Run `python scripts/seed_api_data.py` against your database and substitute these IDs:",
        "",
        "```json",
        json.dumps({k: v for k, v in vars(seed).items()}, indent=2, default=str),
        "```",
        "",
        "## Table of contents",
        "",
    ]

    ordered = FOLDER_ORDER + sorted(set(folders) - set(FOLDER_ORDER))
    for folder in ordered:
        if folder not in folders:
            continue
        lines.append(f"- [{folder}](#{folder.lower().replace(' ', '-').replace('&', '')})")
        for method, path in folders[folder]:
            lines.append(f"  - [{method} {path}](#{_anchor(method, path)})")

    lines.append("")

    for folder in ordered:
        if folder not in folders:
            continue
        lines.extend([f"## {folder}", ""])
        for method, path in sorted(folders[folder], key=lambda x: (x[1], x[0])):
            response = _call_route(client, method, path)
            status, output = _format_output(response)
            lines.extend(
                [
                    f"### {method} `{path}` {{#{_anchor(method, path)}}}",
                    "",
                    _format_input(method, path),
                    "**cURL**",
                    "",
                    "```bash",
                    _build_curl(base_url, method, path),
                    "```",
                    "",
                    f"**Example response** (`{status}`)",
                    "",
                    output,
                    "",
                    "---",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate API markdown with curl examples.")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL shown in curl examples",
    )
    parser.add_argument(
        "--output",
        default=str(OUT_PATH),
        help="Output markdown path",
    )
    args = parser.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generate_markdown(args.base_url), encoding="utf-8")
    print(f"Wrote {out} ({API_ROUTE_COUNT} endpoints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
