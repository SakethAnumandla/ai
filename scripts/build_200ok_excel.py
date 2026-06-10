#!/usr/bin/env python3
"""Build API_200OK_LIST.xlsx from Newman log or route inventory."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "API_200OK_LIST.xlsx"
LOG = Path(
    "/Users/admin/.cursor/projects/Users-admin-Desktop-bizwy-expense-backend-New-main/terminals/895033.txt"
)
BASE = "https://api.bizwy.in"

SUCCESS = re.compile(
    r"^\s*(GET|POST|PUT|PATCH|DELETE)\s+(https://\S+)\s+\[(\d+)\s+([^,\]]+)",
    re.IGNORECASE,
)
NAME = re.compile(r"^↳\s+(.+)$")


def parse_newman_log(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict] = []
    current_name = ""
    for i, line in enumerate(lines):
        m_name = NAME.match(line)
        if m_name:
            current_name = m_name.group(1).strip()
            continue
        m = SUCCESS.search(line)
        if not m and line.strip().startswith("[") and i > 0:
            # Newman sometimes splits: URL line then "[201 Created, ...]" on next line
            combined = lines[i - 1] + " " + line
            m = SUCCESS.search(combined)
        if not m and i + 1 < len(lines) and "http" in line:
            combined = line + " " + lines[i + 1]
            m = SUCCESS.search(combined)
        if not m:
            continue
        method, url, code_s, status_text = m.groups()
        code = int(code_s)
        if not (200 <= code < 300):
            continue
        path_only = url.replace(BASE, "").split("?")[0] or "/"
        rows.append(
            {
                "name": current_name or f"{method} {path_only}",
                "method": method.upper(),
                "path": path_only,
                "full_url": url,
                "status_code": code,
                "status_text": status_text.strip(),
            }
        )
    return rows


def all_routes() -> list[dict]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.main import app

    rows = []
    for route in app.routes:
        if not hasattr(route, "methods") or not hasattr(route, "path"):
            continue
        if route.path in {"/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect"}:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            rows.append(
                {
                    "name": f"{method} {route.path}",
                    "method": method,
                    "path": route.path,
                    "full_url": f"{BASE}{route.path}",
                    "status_code": "",
                    "status_text": "Registered route",
                }
            )
    rows.sort(key=lambda r: (r["path"], r["method"]))
    return rows


def write_excel(ok_rows: list[dict], all_rows: list[dict]) -> None:
    wb = Workbook()
    headers = ["S.No", "API Name", "Method", "Path", "Full URL", "Status Code", "Status Text"]
    hfill = PatternFill("solid", fgColor="1F4E79")
    hfont = Font(color="FFFFFF", bold=True)

    ws = wb.active
    ws.title = "200 OK APIs"
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(1, c)
        cell.fill = hfill
        cell.font = hfont
        cell.alignment = Alignment(horizontal="center")
    for i, r in enumerate(ok_rows, 1):
        ws.append([i, r["name"], r["method"], r["path"], r["full_url"], r["status_code"], r["status_text"]])

    ws2 = wb.create_sheet("All Registered APIs")
    ws2.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws2.cell(1, c)
        cell.fill = hfill
        cell.font = hfont
    for i, r in enumerate(all_rows, 1):
        ws2.append([i, r["name"], r["method"], r["path"], r["full_url"], r["status_code"], r["status_text"]])

    meta = wb.create_sheet("Summary")
    meta.append(["Field", "Value"])
    meta.append(["Production Base URL", BASE])
    meta.append(["Test Date", "2026-06-10"])
    meta.append(["Source", "Postman/Newman production run"])
    meta.append(["200 OK (2xx) APIs", len(ok_rows)])
    meta.append(["Total Registered APIs", len(all_rows)])
    meta.append(["Generated At (UTC)", datetime.now(timezone.utc).isoformat()])
    meta.append(["Note", "Production was 502 at re-export time; list from last successful Newman run"])

    for sheet in (ws, ws2):
        for col in sheet.columns:
            w = min(max(len(str(c.value or "")) for c in col) + 2, 70)
            sheet.column_dimensions[col[0].column_letter].width = w

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUTPUT)
    print(f"Saved {len(ok_rows)} rows -> {OUTPUT}")


def main() -> int:
    ok = parse_newman_log(LOG)
    if not ok:
        print("No 2xx rows parsed from log", file=sys.stderr)
        return 1
    all_rows = all_routes()
    write_excel(ok, all_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
