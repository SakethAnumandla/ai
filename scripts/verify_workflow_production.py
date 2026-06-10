"""Verify workflow + OCR-critical URLs on any expense API host (default: production).

Usage:
  python3 scripts/verify_workflow_production.py
  python3 scripts/verify_workflow_production.py http://127.0.0.1:8000
"""
from __future__ import annotations

import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://api.bizwy.in"

PATHS = [
    "/health",
    "/categories/business/hierarchy",
    "/expenses/approvers/directory",
    "/expenses/approvals/pending",
    "/budgets/monthly?financial_year=FY2025-26",
    "/wallet/budget-utilisation",
    "/dashboard/export-by-fy?financial_year=FY2025-26&group_by=month",
    "/dashboard/export-data?period=this_month&format=json",
    "/ai/chat/sessions",
]


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=45.0)
    print(f"Production readiness check: {BASE}\n")
    failed = 0
    for path in PATHS:
        r = client.get(path)
        ok = r.status_code == 200
        if not ok:
            failed += 1
        tag = "OK " if ok else "FAIL"
        extra = ""
        if ok and "hierarchy" in path:
            data = r.json()
            mains = data.get("main_categories") or []
            extra = f" ({len(mains)} main categories)"
        elif ok and "pending" in path:
            data = r.json()
            count = data.get("count", len(data.get("pending") or []))
            extra = f" (count={count})"
        elif ok and "export-by-fy" in path:
            data = r.json()
            extra = f" (groups={len(data.get('groups') or {})})"
        elif ok and "chat/sessions" in path:
            data = r.json()
            sessions = data if isinstance(data, list) else data.get("sessions") or []
            extra = f" (sessions={len(sessions)})"
        print(f"  {tag} {r.status_code} {path}{extra}")
        if not ok:
            print(f"       {r.text[:160]}")
    print()
    if failed:
        print(
            f"{failed} endpoint(s) missing or failing — redeploy latest backend to this host."
        )
        return 1
    print("All workflow endpoints are live and ready for production.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
