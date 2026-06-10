"""Re-run the 14 Flutter smoke-test endpoints and print status + body summary."""
import json
import sys
from io import BytesIO

import httpx

BASE = "http://localhost:8000"
TIMEOUT = 120.0
png = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
    "7753de0000000c49444154789c6360010000050001a5a5a5a300000000"
    "49454e44ae426082"
)


def run(name: str, fn) -> dict:
    try:
        r = fn()
        body = ""
        try:
            data = r.json()
            body = json.dumps(data, default=str)[:200]
        except Exception:
            body = (r.text or "")[:200]
        return {
            "endpoint": name,
            "status": r.status_code,
            "ok": 200 <= r.status_code < 300,
            "body_preview": body,
        }
    except Exception as e:
        return {
            "endpoint": name,
            "status": "ERR",
            "ok": False,
            "body_preview": str(e)[:200],
        }


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=TIMEOUT)
    rows = []
    expense_id = None

    rows.append(run("GET /", lambda: c.get("/")))
    rows.append(run("GET /categories", lambda: c.get("/categories")))
    rows.append(run("GET /dashboard/stats", lambda: c.get("/dashboard/stats")))
    rows.append(
        run(
            "GET /dashboard/category-breakdown",
            lambda: c.get("/dashboard/category-breakdown"),
        )
    )
    rows.append(
        run(
            "GET /dashboard/recent-transactions",
            lambda: c.get("/dashboard/recent-transactions"),
        )
    )
    rows.append(run("GET /expenses", lambda: c.get("/expenses")))
    rows.append(run("GET /expenses/drafts", lambda: c.get("/expenses/drafts")))
    rows.append(run("GET /wallet/balance", lambda: c.get("/wallet/balance")))
    rows.append(run("GET /wallet/transactions", lambda: c.get("/wallet/transactions")))

    r = c.post(
        "/expenses/manual",
        data={
            "bill_name": "Flutter test bill",
            "bill_amount": "42",
            "bill_date": "15/05/2026",
            "transaction_type": "out",
            "main_category": "miscellaneous",
            "save_as_draft": "true",
        },
    )
    rows.append(
        {
            "endpoint": "POST /expenses/manual",
            "status": r.status_code,
            "ok": r.status_code in (200, 201),
            "body_preview": json.dumps(r.json(), default=str)[:200] if r.status_code < 500 else r.text[:200],
        }
    )
    if r.status_code in (200, 201):
        expense_id = r.json().get("id")

    if expense_id:
        rows.append(
            run(f"GET /expenses/{expense_id}", lambda: c.get(f"/expenses/{expense_id}"))
        )
        rows.append(
            run(
                f"GET /expenses/{expense_id}/details",
                lambda: c.get(f"/expenses/{expense_id}/details"),
            )
        )
        dr = c.delete(f"/expenses/{expense_id}")
        rows.append(
            {
                "endpoint": f"DELETE /expenses/{expense_id}",
                "status": dr.status_code,
                "ok": dr.status_code in (200, 204),
                "body_preview": dr.text[:200] or "(empty)",
            }
        )

    rows.append(
        run(
            "POST /ocr/scan",
            lambda: c.post(
                "/ocr/scan",
                files={"file": ("tiny.png", png, "image/png")},
            ),
        )
    )

    print(f"\n{'Endpoint':<42} {'Status':<8} {'OK':<5} Preview")
    print("-" * 100)
    passed = 0
    for row in rows:
        ok = "yes" if row["ok"] else "no"
        if row["ok"]:
            passed += 1
        print(
            f"{row['endpoint']:<42} {str(row['status']):<8} {ok:<5} {row['body_preview'][:55]}"
        )
    print("-" * 100)
    print(f"Passed: {passed}/{len(rows)}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
