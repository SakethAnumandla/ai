"""End-to-end test: manual bill + approve + dashboard/wallet APIs."""
import json
import sys
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
IMAGE = Path(
    r"C:\Users\Lenovo\.cursor\projects\c-expense-backend\assets"
    r"\c__Users_Lenovo_AppData_Roaming_Cursor_User_workspaceStorage_938f21277c48aac2d541a06ef08a303f_images"
    r"_Screenshot_2026-05-15_140200-057b35bf-f269-4d60-9cbd-d6851f1c7627.png"
)


def pp(title: str, data):
    print(f"\n=== {title} ===")
    print(json.dumps(data, indent=2, default=str))


def main():
    if not IMAGE.exists():
        print(f"Image not found: {IMAGE}", file=sys.stderr)
        sys.exit(1)

    with httpx.Client(timeout=120.0) as client:
        pp("Health", client.get(f"{BASE}/health").json())

        with IMAGE.open("rb") as f:
            files = [("files", (IMAGE.name, f, "image/png"))]
            data = {
                "bill_name": "Ankita Bill",
                "bill_amount": "832.7",
                "bill_date": "15/05/2026",
                "transaction_type": "out",
                "main_category": "travel",
                "sub_category": "uber",
                "description": "mumbai travel cab bill",
                "vendor_name": "Uber",
                "save_as_draft": "false",
            }
            r = client.post(f"{BASE}/expenses/manual", data=data, files=files)
            print(f"\n=== Create expense (POST /expenses/manual) status={r.status_code} ===")
            if r.status_code != 201:
                print(r.text)
                sys.exit(1)
            expense = r.json()
            pp("Created expense", expense)

        eid = expense["id"]

        r = client.post(
            f"{BASE}/expenses/{eid}/approve",
            json={"status": "approved", "rejection_reason": None},
        )
        print(f"\n=== Approve (POST /expenses/{eid}/approve) status={r.status_code} ===")
        if r.status_code == 200:
            pp("Approved expense", r.json())
        else:
            print(r.text)

        endpoints = [
            ("GET expense", f"/expenses/{eid}"),
            ("List expenses", "/expenses?limit=10"),
            ("Expense files", f"/expenses/{eid}/files"),
            ("Wallet balance", "/wallet/balance"),
            ("Wallet transactions", "/wallet/transactions"),
            ("Wallet summary", "/wallet/summary"),
            ("Dashboard stats", "/dashboard/stats"),
            ("Category breakdown", "/dashboard/category-breakdown?period=month"),
            ("Monthly trend", "/dashboard/monthly-trend?months=6"),
            ("Recent transactions", "/dashboard/recent-transactions?limit=5"),
            ("Top categories", "/dashboard/top-categories"),
            ("Daily spending", "/dashboard/daily-spending?days=30"),
            ("Pending approvals", "/dashboard/pending-approvals-summary"),
            ("Quick insights", "/dashboard/quick-insights"),
        ]

        for title, path in endpoints:
            resp = client.get(f"{BASE}{path}")
            print(f"\n=== {title} ({path}) status={resp.status_code} ===")
            if resp.status_code == 200:
                try:
                    print(json.dumps(resp.json(), indent=2, default=str)[:4000])
                except Exception:
                    print(resp.text[:2000])
            else:
                print(resp.text[:500])


if __name__ == "__main__":
    main()
