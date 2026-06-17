#!/usr/bin/env python3
"""Finish saving OCR expense #47 and manual expense #48."""
from __future__ import annotations

import json
import mimetypes
import urllib.parse
import urllib.request
from pathlib import Path

from app.database import SessionLocal
from app.models import Expense, MainCategory, User
from app.schemas import ExpenseSubmit
from app.services.expense_service import ExpenseService
from app.utils.expense_helpers import attach_files_to_expense

ASSETS = Path("/Users/admin/.cursor/projects/Users-admin-Desktop-bizwy-expense-backend-New-main/assets")
MANUAL_RECEIPT = ASSETS / "WhatsApp_Image_2026-06-16_at_10.05.13_AM-b33e4367-1df2-4141-a8f3-867fdd45f968.png"
BASE = "http://127.0.0.1:8000"
USER_ID = 39120


def _submit_expense(expense: Expense) -> Expense:
    svc = ExpenseService(db)
    body = ExpenseSubmit(
        bill_name=expense.bill_name,
        bill_amount=float(expense.bill_amount),
        bill_date=expense.bill_date,
        main_category=expense.main_category or MainCategory.MISCELLANEOUS,
        sub_category=expense.sub_category,
        line_item=expense.line_item,
        description=expense.description,
        vendor_name=expense.vendor_name,
        tax_amount=float(expense.tax_amount or 0),
        submitted_by_name=expense.submitted_by_name,
        submitted_by_role=expense.submitted_by_role,
        payment_method=expense.payment_method.value if expense.payment_method else "cash",
        confirm_submit=False,
        save_as_draft=False,
        auto_approve=True,
    )
    return svc.submit_draft(
        expense.id,
        expense.user_id,
        body,
        company_id=expense.company_id,
    )


db = SessionLocal()
user = db.query(User).filter(User.id == USER_ID).first()

# Manual expense #48 — attach receipt
manual = db.query(Expense).filter(Expense.id == 48, Expense.user_id == USER_ID).first()
if manual and not manual.files:
    raw = MANUAL_RECEIPT.read_bytes()
    file_info = {
        "file_name": MANUAL_RECEIPT.name,
        "file_data": raw,
        "file_size": len(raw),
        "mime_type": mimetypes.guess_type(MANUAL_RECEIPT.name)[0] or "image/png",
        "is_primary": True,
    }
    attach_files_to_expense(db, manual, [file_info])
    manual.description = "Restaurant lunch bill from Sunrise Foods"
    db.commit()
    db.refresh(manual)
    print(f"Attached bill to expense #{manual.id}, files={len(manual.files)}")

manual_saved = _submit_expense(manual)
print(
    f"Manual saved: id={manual_saved.id} status={manual_saved.status.value} "
    f"amount={manual_saved.bill_amount} files={len(manual_saved.files)}"
)

# OCR expense #47 — already has receipt
ocr = db.query(Expense).filter(Expense.id == 47, Expense.user_id == USER_ID).first()
if ocr:
    ocr.company_id = 12
    db.commit()
    ocr_saved = _submit_expense(ocr)
    print(
        f"OCR saved: id={ocr_saved.id} status={ocr_saved.status.value} "
        f"amount={ocr_saved.bill_amount} vendor={ocr_saved.vendor_name} "
        f"files={len(ocr_saved.files)} method={ocr_saved.upload_method.value}"
    )

db.close()

# Verify via API
for eid in (47, 48):
    url = f"{BASE}/expenses/{eid}?{urllib.parse.urlencode({'user_id': USER_ID, 'company_id': 12})}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    print(
        f"API #{eid}: status={data['status']} name={data['bill_name']} "
        f"amount={data['bill_amount']} files={len(data.get('files') or [])} "
        f"preview={bool(data.get('preview_url'))}"
    )
