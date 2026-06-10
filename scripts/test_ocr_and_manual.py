"""Test one OCR expense and one manual expense with receipt images."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

BASE = os.environ.get("EXPENSE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FOOD1 = FIXTURES / "food1_receipt.png"
FOOD2 = FIXTURES / "food2_receipt.png"


def main() -> int:
    results: dict = {}

    with httpx.Client(base_url=BASE, timeout=300.0) as client:
        h = client.get("/health")
        print("HEALTH:", h.status_code, h.json().get("status"))

        print("\n=== TEST 1: OCR scan (food1 - Sunrise Foods receipt) ===")
        with FOOD1.open("rb") as f:
            r = client.post(
                "/ocr/scan",
                files={"file": (FOOD1.name, f, "image/png")},
                params={"as_draft": "true", "auto_approve": "false", "force_rescan": "true"},
            )
        print("Status:", r.status_code)
        if r.status_code not in (200, 201):
            print("Error:", r.text[:1500])
            results["ocr"] = {"ok": False, "status": r.status_code, "error": r.text[:500]}
        else:
            ocr_exp = r.json()
            ocr_id = ocr_exp.get("id")
            print("Expense ID:", ocr_id)
            print("Bill name:", ocr_exp.get("bill_name"))
            print("Amount:", ocr_exp.get("bill_amount"))
            print("Vendor:", ocr_exp.get("vendor_name"))
            print("Upload method:", ocr_exp.get("upload_method"))
            print("Status:", ocr_exp.get("status"))
            g = client.get(f"/expenses/{ocr_id}")
            print("GET verify:", g.status_code)
            results["ocr"] = {
                "ok": g.status_code == 200,
                "id": ocr_id,
                "bill_name": ocr_exp.get("bill_name"),
                "bill_amount": ocr_exp.get("bill_amount"),
                "vendor_name": ocr_exp.get("vendor_name"),
                "upload_method": ocr_exp.get("upload_method"),
                "status": ocr_exp.get("status"),
                "saved_in_db": g.status_code == 200,
            }

        print("\n=== TEST 2: Manual upload (food2 - Restaurant Food Bill) ===")
        with FOOD2.open("rb") as f:
            r2 = client.post(
                "/expenses/manual",
                data={
                    "bill_name": "Restaurant Food Bill",
                    "bill_amount": "514.50",
                    "bill_date": "24/04/2024",
                    "main_category": "meals_entertainment",
                    "sub_category": "restaurant",
                    "vendor_name": "Restaurant",
                    "bill_number": "1304",
                    "description": "Paneer Butter Masala, Veg Biryani, Tandoori Roti, Gulab Jamun",
                    "tax_amount": "24.50",
                    "subtotal": "490.00",
                    "save_as_draft": "true",
                },
                files=[("files", (FOOD2.name, f, "image/png"))],
            )
        print("Status:", r2.status_code)
        if r2.status_code not in (200, 201):
            print("Error:", r2.text[:1500])
            results["manual"] = {"ok": False, "status": r2.status_code, "error": r2.text[:500]}
        else:
            man_exp = r2.json()
            man_id = man_exp.get("id")
            print("Expense ID:", man_id)
            print("Bill name:", man_exp.get("bill_name"))
            print("Amount:", man_exp.get("bill_amount"))
            print("Vendor:", man_exp.get("vendor_name"))
            print("Upload method:", man_exp.get("upload_method"))
            print("Status:", man_exp.get("status"))
            g2 = client.get(f"/expenses/{man_id}")
            print("GET verify:", g2.status_code)
            if g2.status_code == 200:
                det = g2.json()
                print("Files attached:", len(det.get("files") or []))
            results["manual"] = {
                "ok": g2.status_code == 200,
                "id": man_id,
                "bill_name": man_exp.get("bill_name"),
                "bill_amount": man_exp.get("bill_amount"),
                "vendor_name": man_exp.get("vendor_name"),
                "upload_method": man_exp.get("upload_method"),
                "status": man_exp.get("status"),
                "saved_in_db": g2.status_code == 200,
            }

    print("\n=== SUMMARY ===")
    print(json.dumps(results, indent=2))
    if not results.get("ocr", {}).get("ok") or not results.get("manual", {}).get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
