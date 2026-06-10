#!/usr/bin/env python3
"""Scan a bill PDF from uploads/ via OCR and persist expense + OCRBill to the database."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR-scan an uploaded bill and save to DB")
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default=str(ROOT / "uploads/bills/Gmail - Invoice for your Ride CRN9476929196.pdf"),
        help="Path to bill PDF",
    )
    parser.add_argument("--force", action="store_true", help="Rescan even if file hash exists")
    parser.add_argument("--user-id", type=int, default=None, help="User id (default: dev user)")
    args = parser.parse_args()

    pdf = Path(args.pdf_path)
    if not pdf.is_file():
        print(json.dumps({"error": f"File not found: {pdf}"}))
        sys.exit(1)

    from app.database import SessionLocal
    from app.dependencies import DEV_USER_USERNAME
    from app.models import Expense, OCRBill, User
    from app.services.ocr_draft_service import create_ocr_draft
    from app.services.ocr_service import OCRProcessor
    import hashlib
    import mimetypes

    content = pdf.read_bytes()
    ext = pdf.suffix.lstrip(".").lower()
    file_info = {
        "file_data": content,
        "file_name": pdf.name,
        "file_size": len(content),
        "mime_type": mimetypes.guess_type(pdf.name)[0] or "application/pdf",
        "file_hash": hashlib.sha256(content).hexdigest(),
        "file_extension": ext,
        "is_primary": True,
    }

    extracted = OCRProcessor().extract_bill_data_sync(str(pdf), ext)
    print("=== OCR extraction ===")
    preview = {k: v for k, v in extracted.items() if k != "raw_text"}
    print(json.dumps(preview, indent=2, default=str))

    db = SessionLocal()
    try:
        user = (
            db.query(User).filter(User.id == args.user_id).first()
            if args.user_id
            else db.query(User).filter(User.username == DEV_USER_USERNAME).first()
        )
        if not user:
            user = db.query(User).order_by(User.id.asc()).first()
        if not user:
            print(json.dumps({"error": "No user in database"}))
            sys.exit(1)

        expense, prefill, is_dup, err = create_ocr_draft(
            db,
            user.id,
            file_info,
            batch_id=None,
            bill_index=1,
            force_rescan=args.force,
        )
        if err:
            print(json.dumps({"error": err}))
            sys.exit(1)

        db.commit()
        db.refresh(expense)
        ocr_bill = (
            db.query(OCRBill)
            .filter(OCRBill.expense_id == expense.id)
            .order_by(OCRBill.id.desc())
            .first()
        )

        result = {
            "user_id": user.id,
            "expense_id": expense.id,
            "ocr_bill_id": ocr_bill.id if ocr_bill else None,
            "is_duplicate": is_dup,
            "status": expense.status.value,
            "bill_name": expense.bill_name,
            "bill_amount": expense.bill_amount,
            "bill_date": expense.bill_date.isoformat() if expense.bill_date else None,
            "vendor_name": expense.vendor_name,
            "bill_number": expense.bill_number,
            "tax_amount": expense.tax_amount,
            "subtotal": expense.subtotal,
            "main_category": expense.main_category.value,
            "sub_category": expense.sub_category,
            "payment_method": (
                expense.payment_method.value if expense.payment_method else None
            ),
            "prefill": prefill,
            "ocr_bill": {
                "ride_distance": ocr_bill.ride_distance if ocr_bill else None,
                "ride_duration": ocr_bill.ride_duration if ocr_bill else None,
                "ride_type": ocr_bill.ride_type if ocr_bill else None,
                "pickup_location": (
                    (ocr_bill.pickup_location or "")[:120] if ocr_bill else None
                ),
                "dropoff_location": (
                    (ocr_bill.dropoff_location or "")[:120] if ocr_bill else None
                ),
                "confidence_score": ocr_bill.confidence_score if ocr_bill else None,
            },
        }
        print("\n=== Saved to database ===")
        print(json.dumps(result, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
