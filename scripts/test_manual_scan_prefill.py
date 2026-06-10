"""Smoke test: POST /expenses/manual/scan prefill fields."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bhagini_receipt.png"
BASE = "http://127.0.0.1:8000"


def main() -> int:
    if not FIXTURE.is_file():
        print(f"Missing fixture: {FIXTURE}")
        return 1

    with FIXTURE.open("rb") as f:
        r = httpx.post(
            f"{BASE}/expenses/manual/scan",
            files={"file": ("bhagini_receipt.png", f, "image/png")},
            params={"force_duplicate": "true"},
            timeout=300.0,
        )

    print("status", r.status_code)
    if r.status_code != 201:
        print(r.text[:500])
        return 1

    pre = r.json().get("prefill") or {}
    checks = {
        "bill_amount": 3150.0,
        "subtotal": 3000.0,
        "payment_method": "cash",
        "main_category": "meals_entertainment",
    }
    ok = True
    for key, expected in checks.items():
        val = pre.get(key)
        if key == "bill_amount" and float(val or 0) != expected:
            print(f"FAIL {key}: {val} (expected {expected})")
            ok = False
        elif key == "subtotal" and float(val or 0) != expected:
            print(f"FAIL {key}: {val} (expected {expected})")
            ok = False
        elif key == "payment_method" and str(val or "").lower() != expected:
            print(f"FAIL {key}: {val} (expected {expected})")
            ok = False
        elif key == "main_category" and str(val or "").lower() != expected:
            print(f"FAIL {key}: {val} (expected {expected})")
            ok = False
        else:
            print(f"OK   {key}: {val}")

    tax_lines = pre.get("tax_lines") or []
    print(f"tax_lines: {len(tax_lines)}", tax_lines[:2])
    if len(tax_lines) < 2:
        print("FAIL tax_lines: expected CGST + SGST")
        ok = False
    else:
        labels = {str(t.get("tax_label", "")).upper() for t in tax_lines}
        if not {"CGST", "SGST"}.issubset(labels):
            print(f"FAIL tax_lines labels: {labels}")
            ok = False
        else:
            print("OK   tax_lines: CGST + SGST present")
    print(json.dumps({k: pre.get(k) for k in sorted(pre.keys())}, indent=2, default=str)[:2000])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
