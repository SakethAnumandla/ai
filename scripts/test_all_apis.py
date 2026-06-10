"""
Complete API smoke test: wallet, dashboard, expenses, OCR (Bhagini receipt),
workflow, policies, claims, and AI chat (OpenAI).

Run inside Docker:
  docker exec expense_backend-backend-1 python scripts/test_all_apis.py

Or locally (backend on :8000):
  pip install httpx && python scripts/test_all_apis.py
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import os

import httpx

BASE = os.environ.get("EXPENSE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 180.0
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RECEIPT_IMAGE = FIXTURES / "bhagini_receipt.png"

results: list[tuple[str, str, int, str]] = []
snapshots: dict[str, object] = {}


def record(method: str, path: str, resp: httpx.Response, note: str = "") -> None:
    detail = ""
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = str(body.get("detail", body))[:100]
        except Exception:
            detail = resp.text[:100]
    results.append((method, path, resp.status_code, note or detail))


def snapshot(key: str, data: object) -> None:
    snapshots[key] = data


def wallet_block(client: httpx.Client, label: str) -> None:
    """Capture wallet balance + summary for report."""
    bal = client.get("/wallet/balance")
    record("GET", f"/wallet/balance ({label})", bal)
    if bal.status_code == 200:
        snapshot(f"wallet_balance_{label}", bal.json())

    summ = client.get("/wallet/summary", params={"time_period": "all_time"})
    record("GET", f"/wallet/summary ({label})", summ)
    if summ.status_code == 200:
        snapshot(f"wallet_summary_{label}", summ.json())

    leg = client.get("/wallet/summary/legacy")
    record("GET", f"/wallet/summary/legacy ({label})", leg)
    if leg.status_code == 200:
        snapshot(f"wallet_legacy_{label}", leg.json())

    tx = client.get("/wallet/transactions", params={"time_period": "all_time", "limit": 5})
    record("GET", f"/wallet/transactions ({label})", tx)
    if tx.status_code == 200:
        snapshot(f"wallet_tx_{label}", tx.json())


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=TIMEOUT)
    session_id = f"sweep-{uuid.uuid4().hex[:24]}"
    expense_id = None
    batch_id = None
    receipt_expense_id = None
    approval_id = None

    end = datetime.utcnow()
    start = end - timedelta(days=90)

    print("=" * 90)
    print("BIZWY EXPENSE BACKEND — FULL API SWEEP")
    print(f"Base URL: {BASE}")
    print(f"Receipt fixture: {RECEIPT_IMAGE} ({'found' if RECEIPT_IMAGE.is_file() else 'MISSING'})")
    print("=" * 90)

    # --- General ---
    record("GET", "/", client.get("/"))
    h = client.get("/health")
    record("GET", "/health", h)
    if h.status_code == 200:
        snapshot("health", h.json())

    record("GET", "/categories", client.get("/categories"))
    record("GET", "/categories/hierarchy", client.get("/categories/hierarchy"))
    record("GET", "/categories/business/hierarchy", client.get("/categories/business/hierarchy"))
    record("GET", "/payment-modes", client.get("/payment-modes"))

    # --- Wallet (before) ---
    print("\n--- Wallet (before tests) ---")
    wallet_block(client, "before")

    # --- Dashboard ---
    record("GET", "/dashboard/stats", client.get("/dashboard/stats"))
    if client.get("/dashboard/stats").status_code == 200:
        snapshot("dashboard_stats", client.get("/dashboard/stats").json())

    record("GET", "/dashboard/category-breakdown", client.get("/dashboard/category-breakdown"))
    record("GET", "/dashboard/monthly-trend", client.get("/dashboard/monthly-trend"))
    record("GET", "/dashboard/recent-transactions", client.get("/dashboard/recent-transactions"))
    record("GET", "/dashboard/top-categories", client.get("/dashboard/top-categories"))
    record("GET", "/dashboard/daily-spending", client.get("/dashboard/daily-spending"))
    record("GET", "/dashboard/pending-approvals-summary", client.get("/dashboard/pending-approvals-summary"))
    record("GET", "/dashboard/ocr-statistics", client.get("/dashboard/ocr-statistics"))
    record("GET", "/dashboard/budget-vs-actual", client.get("/dashboard/budget-vs-actual"))
    record("GET", "/dashboard/quick-insights", client.get("/dashboard/quick-insights"))
    record(
        "GET",
        "/dashboard/export-data",
        client.get(
            "/dashboard/export-data",
            params={
                "start_date": start.isoformat() + "Z",
                "end_date": end.isoformat() + "Z",
                "format": "json",
            },
        ),
    )
    record(
        "GET",
        "/dashboard/export-by-fy",
        client.get(
            "/dashboard/export-by-fy",
            params={"financial_year": "FY2025-26", "group_by": "month"},
        ),
    )

    # --- Workflow ---
    record("GET", "/expenses/approvers/directory", client.get("/expenses/approvers/directory"))
    pend = client.get("/expenses/approvals/pending")
    record("GET", "/expenses/approvals/pending", pend)
    if pend.status_code == 200:
        snapshot("pending_approvals", pend.json())
        pending_list = pend.json().get("pending") or []
        if pending_list:
            approval_id = pending_list[0].get("approval_id")
            receipt_expense_id = pending_list[0].get("expense_id")

    record(
        "GET",
        "/budgets/monthly",
        client.get("/budgets/monthly", params={"financial_year": "FY2025-26"}),
    )

    # --- Bhagini receipt (real image) ---
    png_minimal = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000"
        "907753de0000000c4949444154789c6360010000050001a5a5a5a300000000"
        "49454e44ae426082"
    )
    receipt_bytes = RECEIPT_IMAGE.read_bytes() if RECEIPT_IMAGE.is_file() else png_minimal
    receipt_name = "bhagini_receipt.png" if RECEIPT_IMAGE.is_file() else "tiny.png"

    print("\n--- OCR / receipt (Bhagini image) ---")
    r_scan = client.post(
        "/ocr/scan",
        files=[("file", (receipt_name, receipt_bytes, "image/png"))],
        params={"auto_approve": "false"},
    )
    record("POST", "/ocr/scan (bhagini receipt)", r_scan)
    if r_scan.status_code in (200, 201):
        snapshot("ocr_scan_bhagini", r_scan.json())
        receipt_expense_id = r_scan.json().get("expense_id") or receipt_expense_id

    r_drafts = client.post(
        "/ocr/scan-drafts",
        files=[("files", (receipt_name, receipt_bytes, "image/png"))],
    )
    record("POST", "/ocr/scan-drafts (bhagini)", r_drafts)
    if r_drafts.status_code == 200:
        snapshot("ocr_scan_drafts", r_drafts.json())
        batch_id = r_drafts.json().get("batch_id")
        bills = r_drafts.json().get("bills") or []
        if bills and not receipt_expense_id:
            receipt_expense_id = bills[0].get("expense_id")

    r_upload = client.post(
        "/expenses/upload-drafts",
        files=[("files", (receipt_name, receipt_bytes, "image/png"))],
    )
    record("POST", "/expenses/upload-drafts (bhagini)", r_upload)
    if r_upload.status_code == 200:
        snapshot("upload_drafts_bhagini", r_upload.json())

    r_mscan = client.post(
        "/expenses/manual/scan",
        files={"file": (receipt_name, receipt_bytes, "image/png")},
        params={"force_duplicate": "true"},
        timeout=300.0,
    )
    mscan_note = ""
    if r_mscan.status_code in (200, 201):
        body = r_mscan.json()
        snapshot("manual_scan_bhagini", body)
        pre = body.get("prefill") or {}
        amt = float(pre.get("bill_amount") or 0)
        sub = pre.get("subtotal")
        tax_lines = pre.get("tax_lines") or []
        if amt != 3150.0:
            mscan_note = f"bill_amount={amt}"
        elif sub is not None and float(sub) != 3000.0:
            mscan_note = f"subtotal={sub}"
        elif len(tax_lines) < 2:
            mscan_note = "tax_lines incomplete"
        receipt_expense_id = body.get("expense_id") or receipt_expense_id
    record("POST", "/expenses/manual/scan (bhagini prefill)", r_mscan, mscan_note)

    # Manual expense with receipt file (fixes prior 400)
    r_manual = client.post(
        "/expenses/manual",
        data={
            "bill_name": "Bhagini API Test",
            "bill_amount": "3150",
            "bill_date": "16/05/2024",
            "transaction_type": "out",
            "main_category": "meals_entertainment",
            "vendor_name": "Bhagini Sriganda Palace",
            "description": "API sweep — Bhagini receipt",
            "save_as_draft": "true",
        },
        files=[("files", (receipt_name, receipt_bytes, "image/png"))],
    )
    record("POST", "/expenses/manual (with receipt file)", r_manual)
    if r_manual.status_code in (200, 201):
        expense_id = r_manual.json().get("id")
        snapshot("manual_expense_bhagini", r_manual.json())

    record("GET", "/expenses", client.get("/expenses"))
    record("GET", "/expenses?status=draft", client.get("/expenses", params={"status": "draft"}))
    drafts_r = client.get("/expenses/drafts")
    record("GET", "/expenses/drafts", drafts_r)
    draft_patch_id = None
    if drafts_r.status_code == 200:
        drafts_body = drafts_r.json()
        items = drafts_body if isinstance(drafts_body, list) else drafts_body.get("items") or []
        if items:
            draft_patch_id = items[0].get("id")

    target_id = expense_id or receipt_expense_id
    if target_id:
        record("GET", f"/expenses/{target_id}", client.get(f"/expenses/{target_id}"))
        record("GET", f"/expenses/{target_id}/details", client.get(f"/expenses/{target_id}/details"))
        record(
            "GET",
            f"/expenses/{target_id}/approval-workflow",
            client.get(f"/expenses/{target_id}/approval-workflow"),
        )
    patch_id = draft_patch_id or expense_id
    if patch_id:
        record(
            "PATCH",
            f"/expenses/{patch_id} (draft)",
            client.patch(
                f"/expenses/{patch_id}",
                json={"description": "patched in API sweep"},
            ),
        )

    record("GET", "/ocr/bills", client.get("/ocr/bills"))
    bills_r = client.get("/ocr/bills")
    if bills_r.status_code == 200 and bills_r.json():
        bid = bills_r.json()[0].get("id")
        record("GET", f"/ocr/bills/{bid}", client.get(f"/ocr/bills/{bid}"))

    if batch_id:
        record("GET", f"/ocr/batch/{batch_id}/drafts", client.get(f"/ocr/batch/{batch_id}/drafts"))
        record("GET", f"/ocr/batch/{batch_id}/status", client.get(f"/ocr/batch/{batch_id}/status"))

    # --- AI chat (OpenAI) ---
    print("\n--- AI chat ---")
    w = client.get("/ai/chat/welcome", params={"session_id": session_id})
    record("GET", "/ai/chat/welcome", w)
    if w.status_code == 200:
        snapshot("chat_welcome", w.json())

    for label, msg in [
        ("greeting", "Hi! How are you?"),
        ("search", "Show my last 5 expenses"),
        ("approvals", "Show expense bills waiting for my approval"),
        ("drafts", "List my draft expenses"),
    ]:
        r = client.post("/ai/chat", json={"session_id": session_id, "message": msg})
        record("POST", f"/ai/chat ({label})", r)
        if r.status_code == 200:
            snapshots[f"chat_{label}"] = {
                "reply": (r.json().get("message") or {}).get("content", "")[:400],
                "tools": [t.get("tool") for t in (r.json().get("tool_results") or [])],
            }

    if RECEIPT_IMAGE.is_file():
        r_chat_up = client.post(
            "/ai/chat/upload",
            data={
                "session_id": session_id,
                "message": "I attached our Bhagini restaurant receipt. Please review OCR and help me save this expense.",
            },
            files=[("files", (receipt_name, receipt_bytes, "image/png"))],
        )
        record("POST", "/ai/chat/upload (bhagini receipt)", r_chat_up)
        if r_chat_up.status_code == 200:
            snapshot("chat_upload_bhagini", {
                "reply": (r_chat_up.json().get("message") or {}).get("content", "")[:500],
                "tool_results": r_chat_up.json().get("tool_results"),
            })

    record("GET", "/ai/chat/sessions", client.get("/ai/chat/sessions", params={"limit": 5}))

    # --- Policies & claims ---
    record("GET", "/policies/types", client.get("/policies/types"))
    record("GET", "/policy-types", client.get("/policy-types"))
    record("GET", "/policies", client.get("/policies"))
    pol = client.post(
        "/policies",
        json={
            "policy_id": f"POL-API-{datetime.utcnow().strftime('%H%M%S')}",
            "policy_name": "API sweep policy",
            "policy_type": "medical",
            "maximum_amount": 5000,
            "sub_category": "healthcare",
            "valid_from": "2025-01-01T00:00:00Z",
        },
    )
    record("POST", "/policies", pol)
    policy_db_id = pol.json().get("id") if pol.status_code == 201 else None
    if policy_db_id:
        record("GET", f"/policies/{policy_db_id}", client.get(f"/policies/{policy_db_id}"))
        r_claim = client.post(
            "/claims/submit",
            data={
                "policy_id": str(policy_db_id),
                "bill_name": "Sweep claim",
                "bill_amount": "500",
                "bill_date": "2025-05-16T00:00:00",
            },
        )
        record("POST", "/claims/submit", r_claim)

    record("GET", "/claims", client.get("/claims"))
    record("GET", "/claims/summary", client.get("/claims/summary"))
    record("GET", "/approvals/pending", client.get("/approvals/pending"))
    record("GET", "/claims/pending-approvals", client.get("/claims/pending-approvals"))

    record("GET", "/expenses/999999", client.get("/expenses/999999"), "expect 404")

    # --- Wallet (after) ---
    print("\n--- Wallet (after tests) ---")
    wallet_block(client, "after")

    # --- Results table ---
    print(f"\n{'METHOD':<8} {'PATH':<52} {'CODE':<6} NOTE")
    print("-" * 100)
    ok = warn = err = 0
    for method, path, code, note in results:
        if 200 <= code < 300:
            ok += 1
        elif code in (400, 404, 422):
            warn += 1
        else:
            err += 1
        print(f"{method:<8} {path:<52} {code:<6} {(note or '')[:38]}")
    print("-" * 100)
    print(f"Total: {len(results)} | 2xx: {ok} | 4xx: {warn} | other: {err}")

    # --- Snapshot report (wallet + key payloads) ---
    print("\n" + "=" * 90)
    print("SNAPSHOT REPORT (wallet & key data)")
    print("=" * 90)

    health = snapshots.get("health") or {}
    print("\n[Health]")
    print(json.dumps(health, indent=2, default=str)[:800])

    for key in ("wallet_balance_before", "wallet_balance_after"):
        if key in snapshots:
            print(f"\n[{key}]")
            print(json.dumps(snapshots[key], indent=2, default=str))

    for key in ("wallet_summary_before", "wallet_summary_after"):
        if key in snapshots:
            print(f"\n[{key}]")
            print(json.dumps(snapshots[key], indent=2, default=str))

    if "dashboard_stats" in snapshots:
        print("\n[Dashboard stats]")
        print(json.dumps(snapshots["dashboard_stats"], indent=2, default=str)[:1200])

    if "ocr_scan_bhagini" in snapshots:
        print("\n[OCR scan — Bhagini receipt]")
        o = snapshots["ocr_scan_bhagini"]
        if isinstance(o, dict):
            print(f"  expense_id: {o.get('id') or o.get('expense_id')}")
            print(f"  bill_name: {o.get('bill_name')}")
            print(f"  bill_amount: {o.get('bill_amount')}")
            print(f"  vendor: {o.get('vendor_name')}")
        else:
            print(json.dumps(o, indent=2, default=str)[:600])

    if "manual_scan_bhagini" in snapshots:
        print("\n[Manual scan prefill — Bhagini receipt]")
        m = snapshots["manual_scan_bhagini"]
        pre = (m.get("prefill") or {}) if isinstance(m, dict) else {}
        print(f"  expense_id: {m.get('expense_id')}")
        print(f"  bill_amount: {pre.get('bill_amount')}")
        print(f"  subtotal: {pre.get('subtotal')}")
        print(f"  tax_lines: {len(pre.get('tax_lines') or [])}")
        print(f"  payment_method: {pre.get('payment_method')}")
        print(f"  main_category: {pre.get('main_category')}")

    if "chat_upload_bhagini" in snapshots:
        print("\n[AI chat upload — Bhagini receipt]")
        print(json.dumps(snapshots["chat_upload_bhagini"], indent=2, default=str)[:800])

    if "pending_approvals" in snapshots:
        print("\n[Pending expense approvals]")
        p = snapshots["pending_approvals"]
        print(f"  count: {p.get('count') if isinstance(p, dict) else '?'}")

    print("\n" + "=" * 90)
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
