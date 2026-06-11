#!/usr/bin/env python3
"""Generate curl commands for every API route and execute them one by one."""
from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_postman_collection import (  # noqa: E402
    SKIP_PATHS,
    SKIP_ROUTE_PREFIXES,
    _collect_routes,
    _file_upload_body,
    _form_body,
    _json_body,
    _path_to_postman,
    _query_params,
)

BASE = os.environ.get("EXPENSE_API_BASE", "http://127.0.0.1:8001").rstrip("/")
TIMEOUT = float(os.environ.get("API_TEST_TIMEOUT", "120"))
REPORT_PATH = ROOT / "docs" / "API_CURL_TEST_REPORT.md"
RECEIPT = ROOT / "scripts" / "fixtures" / "receipt.png"
VOICE = ROOT / "scripts" / "fixtures" / "sample.webm"


@dataclass
class Vars:
    data: Dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.data.get(key, default)

    def substitute(self, text: str) -> str:
        out = text
        for key, value in sorted(self.data.items(), key=lambda kv: -len(kv[0])):
            out = out.replace(f"{{{{{key}}}}}", str(value))
        return out


def _bootstrap(client: httpx.Client, vars_: Vars) -> None:
    r = client.post("/api-test/bootstrap")
    if r.status_code != 200:
        raise RuntimeError(f"Bootstrap failed: {r.status_code} {r.text[:500]}")
    ids = r.json().get("ids") or {}
    for k, v in ids.items():
        if v is not None and v != "":
            vars_.data[k] = str(v)
    vars_.data.setdefault("base_url", BASE)
    vars_.data.setdefault("category", "meals_entertainment")
    vars_.data.setdefault("financial_year", "FY2025-26")
    vars_.data.setdefault("session_id", vars_.data.get("session_id") or f"curl-{uuid.uuid4().hex[:12]}")
    vars_.data.setdefault("unique_suffix", uuid.uuid4().hex[:8].upper())


def _resolve_path(path: str, method: str, vars_: Vars) -> str:
    return vars_.substitute(_path_to_postman(path, method))


def _resolve_query(path: str, vars_: Vars) -> Dict[str, str]:
    params: Dict[str, str] = {}
    for item in _query_params(path):
        if item.get("disabled"):
            continue
        params[item["key"]] = vars_.substitute(str(item["value"]))
    if path == "/ai/chat/end":
        params["session_id"] = vars_.get("session_id")
    return params


def _resolve_json(method: str, path: str, vars_: Vars) -> Optional[str]:
    raw = _json_body(method, path)
    if raw is None:
        return None
    return vars_.substitute(raw)


def _resolve_files(path: str) -> List[Tuple[str, Path, str]]:
    rows: List[Tuple[str, Path, str]] = []
    form = _form_body(path) or []
    uploads = _file_upload_body(path) or []
    for item in form + uploads:
        if item.get("type") != "file":
            continue
        src = item.get("src", "")
        p = ROOT / src if not Path(src).is_absolute() else Path(src)
        if not p.is_file():
            p = RECEIPT
        mime = "image/png" if p.suffix.lower() == ".png" else "application/octet-stream"
        if "webm" in str(p):
            mime = "audio/webm"
        rows.append((item["key"], p, mime))
    return rows


def _resolve_form_fields(path: str, vars_: Vars) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    form = _form_body(path) or []
    for item in form:
        if item.get("type") == "file":
            continue
        fields[item["key"]] = vars_.substitute(str(item.get("value", "")))
    if path == "/ocr/scan-batch":
        fields.setdefault("batch_name", "curl-batch")
    return fields


def build_curl(
    method: str,
    path: str,
    vars_: Vars,
) -> Tuple[str, Dict[str, Any]]:
    """Return (curl_command, httpx_kwargs)."""
    url_path = _resolve_path(path, method, vars_)
    query = _resolve_query(path, vars_)
    url = f"{BASE}{url_path}"
    if query:
        url = f"{url}?{urlencode(query)}"

    parts = ["curl", "-s", "-w", r"'\\nHTTP_CODE:%{http_code}\\n'", "-X", method, f"'{url}'"]
    headers: Dict[str, str] = {}
    httpx_kwargs: Dict[str, Any] = {"method": method, "url": url_path, "params": query or None}

    json_raw = _resolve_json(method, path, vars_)
    form_fields = _resolve_form_fields(path, vars_)
    file_rows = _resolve_files(path)

    if file_rows or form_fields:
        for key, value in form_fields.items():
            parts.extend(["-F", f"'{key}={value}'"])
        for key, fpath, mime in file_rows:
            parts.extend(["-F", f"'{key}=@{fpath};type={mime}'"])
        files = []
        data = {}
        for key, value in form_fields.items():
            data[key] = value
        for key, fpath, mime in file_rows:
            files.append((key, (fpath.name, fpath.read_bytes(), mime)))
        httpx_kwargs["data"] = data or None
        httpx_kwargs["files"] = files or None
    elif json_raw is not None and method in ("POST", "PUT", "PATCH"):
        parts.extend(["-H", "'Content-Type: application/json'", "-d", f"'{json_raw}'"])
        headers["Content-Type"] = "application/json"
        httpx_kwargs["content"] = json_raw

    curl = " ".join(parts)
    if headers:
        httpx_kwargs["headers"] = headers
    return curl, httpx_kwargs


@dataclass
class Result:
    method: str
    path: str
    status: int
    curl: str
    note: str = ""


def run_all() -> Tuple[List[Result], Vars]:
    vars_ = Vars()
    results: List[Result] = []

    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as client:
        _bootstrap(client, vars_)

        routes = _collect_routes()
        # Legacy approve must run before workflow action consumes the pending step.
        route_rank = {
            ("POST", "/expenses/approvals/{approval_id}/action"): 0,
            ("PUT", "/expenses/{expense_id}/taxes"): 1,
            ("PATCH", "/expenses/{expense_id}"): 2,
            ("POST", "/expenses/{expense_id}/submit"): 3,
        }
        routes.sort(key=lambda item: (route_rank.get(item, 99), item[1], item[0]))

        # Skip destructive / duplicate-prone routes on full sweep
        skip_exact = {
            ("DELETE", "/expenses/{expense_id}"),
            ("DELETE", "/expenses/{expense_id}/files/{file_id}"),
            ("DELETE", "/policies/{policy_id}"),
            ("POST", "/expenses/{expense_id}/discard"),
            ("POST", "/ai/chat/end"),
            # Legacy alias — same flow as /expenses/approvals/{id}/action (already tested).
            ("POST", "/expenses/{expense_id}/approve"),
        }

        for method, path in routes:
            if path in SKIP_PATHS:
                continue
            if any(path.startswith(p) for p in SKIP_ROUTE_PREFIXES):
                continue
            if (method, path) in skip_exact:
                curl, kwargs = build_curl(method, path, vars_)
                results.append(Result(method, path, 0, curl, "skipped (destructive)"))
                continue

            curl, kwargs = build_curl(method, path, vars_)
            try:
                resp = client.request(**kwargs)
                note = ""
                if resp.status_code >= 400:
                    try:
                        note = str(resp.json().get("detail", resp.text))[:120]
                    except Exception:
                        note = resp.text[:120]
                results.append(Result(method, path, resp.status_code, curl, note))

                # Refresh dynamic IDs when possible
                if path == "/manager/bulk-preview/export" and resp.status_code < 300:
                    body = resp.json()
                    eid = body.get("export_id") or body.get("id")
                    if eid:
                        vars_.data["bulk_export_id"] = str(eid)
                if path == "/finance/alerts/evaluate" and resp.status_code < 300:
                    body = resp.json()
                    alerts = body.get("alerts") or []
                    if alerts and alerts[0].get("id"):
                        vars_.data["alert_id"] = str(alerts[0]["id"])
                if path == "/finance/snapshots/capture" and resp.status_code < 300:
                    body = resp.json()
                    sid = body.get("snapshot_id") or body.get("id")
                    if sid:
                        vars_.data["snapshot_a_id"] = str(sid)
            except Exception as exc:
                results.append(Result(method, path, 0, curl, f"error: {exc}"))

    return results, vars_


def write_report(results: List[Result], vars_: Vars) -> None:
    ok = sum(1 for r in results if 200 <= r.status < 300)
    warn = sum(1 for r in results if r.status in (0,) or (400 <= r.status < 500))
    err = sum(1 for r in results if r.status >= 500)
    skipped = sum(1 for r in results if r.status == 0)

    lines = [
        "# API Curl Test Report",
        "",
        f"- **Base URL:** `{BASE}`",
        f"- **Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"- **Total tested:** {len(results)}",
        f"- **2xx:** {ok} | **4xx:** {warn} | **5xx+:** {err} | **Skipped/Error:** {skipped}",
        "",
        "## Bootstrap IDs",
        "",
        "```json",
        json.dumps(vars_.data, indent=2),
        "```",
        "",
        "## Results",
        "",
        "| # | Method | Path | Status | Note |",
        "|---|--------|------|--------|------|",
    ]
    for i, r in enumerate(results, 1):
        status = "SKIP" if r.status == 0 else str(r.status)
        note = (r.note or "").replace("|", "\\|")[:80]
        lines.append(f"| {i} | {r.method} | `{r.path}` | {status} | {note} |")

    lines.extend(["", "## Curl commands (one per API)", ""])
    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. {r.method} {r.path}")
        lines.append("")
        lines.append("```bash")
        lines.append(r.curl)
        lines.append("```")
        lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report saved: {REPORT_PATH}")


def main() -> int:
    print(f"Testing all APIs against {BASE}")
    results, vars_ = run_all()
    write_report(results, vars_)

    ok = sum(1 for r in results if 200 <= r.status < 300)
    skipped = sum(1 for r in results if r.status == 0)
    failed = sum(1 for r in results if r.status >= 400)
    print(f"\n{'METHOD':<8} {'PATH':<48} {'CODE':<6} NOTE")
    print("-" * 100)
    for r in results:
        code = "SKIP" if r.status == 0 else str(r.status)
        print(f"{r.method:<8} {r.path:<48} {code:<6} {(r.note or '')[:40]}")
    print("-" * 100)
    print(f"Total: {len(results)} | 2xx: {ok} | skipped: {skipped} | failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
