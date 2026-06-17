#!/usr/bin/env python3
"""Smoke-test hosted Bizwy Expense API (GET endpoints + manual/chat expense creation)."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else "https://api.bizwy.in").rstrip("/")
USER_ID = int(sys.argv[2]) if len(sys.argv) > 2 else 1
COMPANY_ID = int(sys.argv[3]) if len(sys.argv) > 3 else 1
TIMEOUT = 90


@dataclass
class Result:
    name: str
    method: str
    path: str
    status: int
    ok: bool
    note: str = ""


results: List[Result] = []


class HttpResponse:
    def __init__(self, status: int, body: bytes, headers: dict):
        self.status_code = status
        self.content = body
        self.text = body.decode("utf-8", errors="replace")
        self.headers = headers
        self.ok = 200 <= status < 300

    def json(self):
        return json.loads(self.text)


def http_request(
    method: str,
    url: str,
    *,
    data: Optional[bytes] = None,
    headers: Optional[dict] = None,
    timeout: int = TIMEOUT,
) -> HttpResponse:
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return HttpResponse(resp.status, resp.read(), dict(resp.headers))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return HttpResponse(exc.code, body, dict(exc.headers))


def qs(extra: str = "") -> str:
    base = f"user_id={USER_ID}&company_id={COMPANY_ID}"
    return f"{base}&{extra}" if extra else base


def check(name: str, method: str, path: str, resp: HttpResponse, *, accept: Tuple[int, ...] = (200,)) -> Result:
    ok = resp.status_code in accept
    note = ""
    if not ok:
        try:
            body = resp.json()
            note = str(body.get("detail", body))[:200]
        except Exception:
            note = (resp.text or "")[:200]
    r = Result(name, method, path, resp.status_code, ok, note)
    results.append(r)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {method} {path} -> {resp.status_code}" + (f" ({note})" if note else ""))
    return r


def get(path: str, name: Optional[str] = None, accept: Tuple[int, ...] = (200,)) -> HttpResponse:
    url = f"{BASE_URL}{path}"
    if "?" in path:
        url = f"{BASE_URL}{path}&user_id={USER_ID}&company_id={COMPANY_ID}" if "user_id=" not in path else f"{BASE_URL}{path}"
    else:
        url = f"{BASE_URL}{path}?{qs()}"
    resp = http_request("GET", url)
    check(name or path, "GET", path, resp, accept=accept)
    return resp


def post_json(path: str, body: dict, name: Optional[str] = None, accept: Tuple[int, ...] = (200, 201)) -> HttpResponse:
    url = f"{BASE_URL}{path}?{qs()}"
    payload = json.dumps(body).encode("utf-8")
    resp = http_request(
        "POST",
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    check(name or path, "POST", path, resp, accept=accept)
    return resp


def post_form(path: str, data: dict, name: Optional[str] = None, accept: Tuple[int, ...] = (200, 201)) -> HttpResponse:
    url = f"{BASE_URL}{path}?{qs()}"
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    resp = http_request(
        "POST",
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    check(name or path, "POST", path, resp, accept=accept)
    return resp


def run_get_smoke() -> Optional[int]:
    """Hit safe GET endpoints; return first expense id if found."""
    print("\n=== Public / health ===")
    check("root", "GET", "/", http_request("GET", f"{BASE_URL}/", timeout=15))
    check("health", "GET", "/health", http_request("GET", f"{BASE_URL}/health", timeout=15))
    check("health/ready", "GET", "/health/ready", http_request("GET", f"{BASE_URL}/health/ready", timeout=15))
    check("categories", "GET", "/categories", http_request("GET", f"{BASE_URL}/categories", timeout=15))
    check("categories/hierarchy", "GET", "/categories/hierarchy", http_request("GET", f"{BASE_URL}/categories/hierarchy", timeout=15))
    check("policy-types", "GET", "/policy-types", http_request("GET", f"{BASE_URL}/policy-types", timeout=15))
    check("payment-modes", "GET", "/payment-modes", http_request("GET", f"{BASE_URL}/payment-modes", timeout=15))

    print("\n=== Scoped GET endpoints ===")
    get("/filters/time-periods")
    get("/categories/business/hierarchy")
    get("/categories/manual")
    get("/tax/config")
    get("/tax/types")
    get("/tax/regimes")
    get("/expenses")
    get("/expenses/drafts")
    get("/expenses/approvers/directory")
    get("/expenses/approvals/pending")
    get("/wallet/balance")
    get("/wallet/transactions")
    get("/wallet/summary")
    get("/wallet/budget-utilisation")
    get("/dashboard/stats")
    get("/dashboard/overview")
    get("/dashboard/category-breakdown")
    get("/dashboard/monthly-trend")
    get("/dashboard/recent-transactions")
    get("/dashboard/top-categories")
    get("/dashboard/daily-spending")
    get("/dashboard/pending-approvals-summary")
    get("/dashboard/ocr-statistics")
    get("/dashboard/budget-vs-actual")
    get("/dashboard/quick-insights")
    get("/policies")
    get("/policies/types")
    get("/claims")
    get("/claims/summary")
    get("/claims/pending-approvals")
    get("/approvals/pending")
    get("/ocr/bills")
    get("/ai/chat/categories")
    get("/ai/chat/sessions")
    get("/ai/memory/explanations")
    get("/ai/memory/confidence")
    get("/ai/memory/audit")
    get("/ai/memory/policy")
    get("/ai/memory/anomalies")
    get("/ai/dead-letter")
    get("/executive/financial-health")
    get("/executive/operational-risks")
    get("/executive/kpi-summary")
    get("/executive/vendor-growth")
    get("/executive/efficiency")
    get("/executive/forecast-summary")
    get("/executive/strategic-recommendations")
    get("/executive/dashboard")
    get("/executive/pack")
    get("/finance/analytics/spend-trends")
    get("/finance/analytics/categories")
    get("/finance/analytics/departments")
    get("/finance/analytics/vendors")
    get("/finance/analytics/policy-violations")
    get("/finance/analytics/approval-health")
    get("/finance/analytics/reimbursements")
    get("/finance/analytics/forecast")
    get("/finance/snapshots")
    get("/finance/alerts")
    get("/finance/reports/versions")
    get("/finance/reports/access-audit")
    get("/manager/analytics/workload-delays")
    get("/manager/analytics/policy-impact")
    get("/manager/approvals/sla-at-risk")
    get("/manager/analytics/forecast")
    get("/expenses/approvers/directory", name="/expenses/approvers/directory (workflow)")
    get("/budgets/monthly", name="/budgets/monthly")

    expense_id: Optional[int] = None
    resp = http_request("GET", f"{BASE_URL}/expenses?{qs()}&period=all_time")
    if resp.ok:
        items = resp.json()
        if items:
            expense_id = items[0].get("id")
            get(f"/expenses/{expense_id}")
            get(f"/expenses/{expense_id}/details")
            get(f"/expenses/{expense_id}/taxes")
            get(f"/expenses/{expense_id}/approval-workflow")
            get(f"/expenses/{expense_id}/approval-remarks")
            get(f"/expenses/{expense_id}/files")
    return expense_id


def create_manual_expense() -> Optional[int]:
    print("\n=== Manual expense creation ===")
    data = {
        "bill_name": f"Smoke Manual {int(time.time())}",
        "bill_amount": "599.00",
        "bill_date": "2026-06-17",
        "main_category": "food",
        "sub_category": "restaurant",
        "vendor_name": "Smoke Test Vendor",
        "description": "Created by smoke_test_all_apis.py on api.bizwy.in",
        "payment_mode": "upi",
        "save_as_draft": "true",
    }
    resp = post_form("/expenses/manual", data, name="POST /expenses/manual")
    if not resp.ok:
        return None
    expense_id = resp.json().get("id")
    print(f"  -> Created manual expense id={expense_id}")
    return expense_id


def chat_message(session_id: str, message: str) -> dict:
    resp = post_json("/ai/chat", {"session_id": session_id, "message": message}, accept=(200,))
    if not resp.ok:
        return {}
    return resp.json()


def extract_preview_expense_id(payload: dict) -> Optional[int]:
    previews = payload.get("expense_previews") or []
    if not previews:
        return None
    card = previews[0]
    return card.get("expense_id") or card.get("id")


def create_chat_expense() -> Optional[int]:
    print("\n=== Chat expense creation ===")
    session_id = f"smoke{uuid.uuid4().hex[:20]}"
    welcome = http_request(
        "GET",
        f"{BASE_URL}/ai/chat/welcome?session_id={session_id}&{qs()}",
    )
    check("chat welcome", "GET", "/ai/chat/welcome", welcome)

    turns = [
        "I spent 850 rupees on Uber ride to client meeting today, travel category",
        "UPI",
        "save as draft",
        "yes",
    ]
    last: dict = {}
    expense_id: Optional[int] = None
    for msg in turns:
        print(f"  User: {msg}")
        last = chat_message(session_id, msg)
        content = (last.get("message") or {}).get("content", "")
        print(f"  Assistant: {content[:200]}")
        expense_id = extract_preview_expense_id(last) or expense_id
        if expense_id:
            print(f"  -> Expense preview id={expense_id}")
            break

    if expense_id:
        return expense_id

    # Try submit action if preview exists with actions
    previews = last.get("expense_previews") or []
    actions = last.get("ui_actions") or []
    if previews and actions:
        action = actions[0].get("action", "submit")
        eid = previews[0].get("expense_id") or previews[0].get("id")
        if eid:
            resp = post_json(
                "/ai/chat/action",
                {"session_id": session_id, "action": action, "expense_id": eid},
                name="POST /ai/chat/action",
            )
            if resp.ok:
                return eid
    return expense_id


def main() -> int:
    print(f"Smoke testing {BASE_URL} (user_id={USER_ID}, company_id={COMPANY_ID})")
    run_get_smoke()
    manual_id = create_manual_expense()
    chat_id = create_chat_expense()

    print("\n=== Summary ===")
    passed = sum(1 for r in results if r.ok)
    failed = [r for r in results if not r.ok]
    print(f"Endpoints checked: {len(results)} | Passed: {passed} | Failed: {len(failed)}")
    if manual_id:
        print(f"Manual expense created: id={manual_id}")
    else:
        print("Manual expense: FAILED")
    if chat_id:
        print(f"Chat expense created: id={chat_id}")
    else:
        print("Chat expense: workflow did not produce preview (may need more turns)")

    if failed:
        print("\nFailed endpoints:")
        for r in failed:
            print(f"  {r.method} {r.path} -> {r.status} {r.note}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
