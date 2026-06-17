#!/usr/bin/env python3
"""Save two expenses via AI chat: one OCR upload, one manual workflow."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
SCOPE = {"user_id": 39120, "company_id": 12}
ASSETS = Path("/Users/admin/.cursor/projects/Users-admin-Desktop-bizwy-expense-backend-New-main/assets")
OCR_RECEIPT = ASSETS / "resaturant2-097e999f-f0be-4ea8-b495-facb3d7f8ff4.png"
MANUAL_RECEIPT = ASSETS / "WhatsApp_Image_2026-06-16_at_10.05.13_AM-b33e4367-1df2-4141-a8f3-867fdd45f968.png"


def _url(path: str, extra: dict | None = None) -> str:
    q = dict(SCOPE)
    if extra:
        q.update(extra)
    return f"{BASE}{path}?{urllib.parse.urlencode(q)}"


def _post_json(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        _url(path),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())


def _upload(session_id: str, file_path: Path, message: str = "") -> dict:
    boundary = f"----bizwy{int(time.time() * 1000)}"
    body = bytearray()
    for name, value in (("session_id", session_id), ("message", message)):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(f"{value}\r\n".encode())
    raw = file_path.read_bytes()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="files"; '
            f'filename="{file_path.name}"\r\n'
        ).encode()
    )
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(raw)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        _url("/ai/chat/upload"),
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def _summarize(label: str, data: dict) -> None:
    print(f"\n=== {label} ===")
    print("Assistant:", (data.get("message") or {}).get("content", "")[:500])
    previews = data.get("expense_previews") or []
    if previews:
        for card in previews:
            print(
                f"  Preview expense_id={card.get('expense_id')} "
                f"name={card.get('bill_name')} amount={card.get('bill_amount')} "
                f"vendor={card.get('vendor_name')} date={card.get('bill_date')} "
                f"bill_attached={card.get('has_bill_attachment')}"
            )
    actions = data.get("ui_actions") or []
    if actions:
        print("  Actions:", [a.get("action") for a in actions])


def run_ocr_expense(session_id: str) -> int | None:
    print(f"\n# OCR expense session={session_id}")
    _post_json("/ai/chat", {"session_id": session_id, "message": "create an expense"})
    _post_json("/ai/chat", {"session_id": session_id, "message": "upload"})
    print("Uploading restaurant receipt (OCR)...")
    result = _upload(session_id, OCR_RECEIPT)
    _summarize("OCR upload result", result)
    previews = result.get("expense_previews") or []
    if not previews:
        print("ERROR: no expense preview from OCR upload", file=sys.stderr)
        return None
    expense_id = previews[0]["expense_id"]
    submit = _post_json(
        "/ai/chat",
        {"session_id": session_id, "message": "save expense"},
    )
    _summarize("OCR submit", submit)
    return expense_id


def run_manual_expense(session_id: str) -> int | None:
    print(f"\n# Manual expense session={session_id}")
    steps = [
        "create an expense",
        "manual",
        "Sunrise Foods lunch",
        "5445.30",
        "Sunrise Foods Pvt Ltd",
        "meals entertainment",
        "business meals",
        "working lunches",
        "0",
        "Abhinav B",
        "Manager",
        "12/02/2026",
        "Restaurant lunch bill from Sunrise Foods",
    ]
    for msg in steps:
        data = _post_json("/ai/chat", {"session_id": session_id, "message": msg})
        print(f"  > {msg!r} -> {(data.get('message') or {}).get('content','')[:120]!r}")

    print("Attaching Sunrise Foods receipt...")
    attach = _upload(session_id, MANUAL_RECEIPT)
    _summarize("Manual attach", attach)
    previews = attach.get("expense_previews") or []
    if not previews:
        print("ERROR: no expense preview after manual attach", file=sys.stderr)
        return None
    expense_id = previews[0]["expense_id"]
    submit = _post_json(
        "/ai/chat",
        {"session_id": session_id, "message": "save expense"},
    )
    _summarize("Manual submit", submit)
    return expense_id


def main() -> int:
    if not OCR_RECEIPT.is_file():
        print(f"Missing OCR receipt: {OCR_RECEIPT}", file=sys.stderr)
        return 1
    if not MANUAL_RECEIPT.is_file():
        print(f"Missing manual receipt: {MANUAL_RECEIPT}", file=sys.stderr)
        return 1

    ts = int(time.time())
    ocr_id = run_ocr_expense(f"ocr-save-{ts}")
    manual_id = run_manual_expense(f"manual-save-{ts}")

    print("\n=== SUMMARY ===")
    print(f"OCR expense id: {ocr_id}")
    print(f"Manual expense id: {manual_id}")

    if not ocr_id or not manual_id:
        return 1

    # Verify saved expenses exist
    for eid in (ocr_id, manual_id):
        req = urllib.request.Request(_url(f"/expenses/{eid}"))
        with urllib.request.urlopen(req, timeout=60) as resp:
            exp = json.loads(resp.read().decode())
        print(
            f"  expense #{eid}: status={exp.get('status')} "
            f"name={exp.get('bill_name')} amount={exp.get('bill_amount')} "
            f"method={exp.get('upload_method')}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"HTTP {exc.code}: {body}", file=sys.stderr)
        raise SystemExit(1)
