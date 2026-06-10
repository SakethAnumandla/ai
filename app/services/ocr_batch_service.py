import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Expense,
    ExpenseFile,
    ExpenseStatus,
    MainCategory,
    OCRBatch,
    OCRBill,
    TransactionType,
    UploadMethod,
)
from app.services.ocr_service import OCRProcessor
from app.services.wallet_service import WalletService
from app.utils.dedup import find_expense_by_file_hash
from app.services.ocr_draft_service import (
    apply_ocr_extract_to_expense,
    build_prefill_dict,
    expense_needs_ocr_refresh,
)
from app.utils.expense_helpers import attach_files_to_expense
from app.utils.ocr_categories import resolve_classification

logger = logging.getLogger(__name__)
ocr_processor = OCRProcessor()


def process_ocr_batch(
    batch_id: int,
    file_payloads: List[Dict[str, Any]],
    user_id: int,
    auto_approve: bool = False,
    force_rescan: bool = False,
) -> None:
    """Background task: OCR each file and create expenses."""
    db: Session = SessionLocal()
    failed_files: List[Dict[str, Any]] = []
    skipped_duplicates: List[Dict[str, Any]] = []
    processed = 0

    try:
        batch = db.query(OCRBatch).filter(OCRBatch.id == batch_id).first()
        if not batch:
            return

        for payload in file_payloads:
            filename = payload["filename"]
            content = payload["content"]
            ext = filename.rsplit(".", 1)[-1].lower()
            tmp_path = None

            try:
                file_hash = payload.get("file_hash")
                refresh_expense: Optional[Expense] = None
                if not force_rescan and file_hash:
                    existing = find_expense_by_file_hash(db, user_id, file_hash)
                    if existing:
                        if not expense_needs_ocr_refresh(existing):
                            skipped_duplicates.append(
                                {
                                    "filename": filename,
                                    "existing_expense_id": existing.id,
                                    "reason": "duplicate_file",
                                }
                            )
                            continue
                        refresh_expense = existing

                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name

                extracted = ocr_processor.extract_bill_data_sync(tmp_path, ext)
                if not extracted.get("total_amount"):
                    failed_files.append(
                        {"filename": filename, "error": "Could not extract bill amount"}
                    )
                    continue

                transaction_type, main_category, sub_category = resolve_classification(
                    extracted, extracted.get("raw_text")
                )
                file_info = {
                    "file_data": content,
                    "file_name": filename,
                    "file_size": len(content),
                    "mime_type": payload.get("mime_type") or "application/octet-stream",
                    "file_hash": payload.get("file_hash"),
                    "thumbnail_data": payload.get("thumbnail_data"),
                    "is_primary": True,
                }

                ocr_bill = OCRBill(
                    user_id=user_id,
                    batch_id=batch_id,
                    original_file_data=content,
                    original_file_name=filename,
                    original_file_size=len(content),
                    original_mime_type=file_info["mime_type"],
                    bill_number=extracted.get("bill_number"),
                    bill_date=extracted.get("bill_date"),
                    vendor_name=extracted.get("vendor_name"),
                    total_amount=extracted.get("total_amount"),
                    tax_amount=extracted.get("tax_amount"),
                    ride_distance=extracted.get("ride_distance"),
                    pickup_location=extracted.get("pickup_location"),
                    dropoff_location=extracted.get("dropoff_location"),
                    restaurant_name=extracted.get("restaurant_name"),
                    items_list=extracted.get("items_list"),
                    raw_text=extracted.get("raw_text"),
                    confidence_score=extracted.get("confidence_score"),
                    detected_main_category=main_category,
                    detected_sub_category=sub_category,
                )
                db.add(ocr_bill)
                db.flush()

                if refresh_expense is not None:
                    prefill = build_prefill_dict(
                        extracted,
                        filename,
                        1,
                        main_category,
                        sub_category,
                        transaction_type,
                    )
                    apply_ocr_extract_to_expense(
                        db, refresh_expense, extracted, prefill
                    )
                    ocr_bill.expense_id = refresh_expense.id
                    continue

                expense = Expense(
                    user_id=user_id,
                    bill_name=f"Bill from {extracted.get('vendor_name', 'Unknown Vendor')}",
                    bill_amount=extracted["total_amount"],
                    bill_date=extracted.get("bill_date") or datetime.utcnow(),
                    transaction_type=transaction_type,
                    main_category=main_category,
                    sub_category=sub_category,
                    description=f"Auto-scanned: {extracted.get('bill_number', 'N/A')}",
                    vendor_name=extracted.get("vendor_name"),
                    bill_number=extracted.get("bill_number"),
                    tax_amount=extracted.get("tax_amount") or 0,
                    upload_method=UploadMethod.OCR,
                    status=ExpenseStatus.APPROVED if auto_approve else ExpenseStatus.PENDING,
                )
                db.add(expense)
                db.flush()

                attach_files_to_expense(db, expense, [file_info])
                ocr_bill.expense_id = expense.id

                if auto_approve:
                    expense.approved_at = datetime.utcnow()
                    WalletService(db).update_wallet_balance(user_id, expense)

                processed += 1
                batch.processed_files = processed
                db.commit()

            except Exception as e:
                logger.exception("OCR batch file failed: %s", filename)
                failed_files.append({"filename": filename, "error": str(e)})
                db.rollback()
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)

        batch = db.query(OCRBatch).filter(OCRBatch.id == batch_id).first()
        if batch:
            batch.processed_files = processed
            if processed > 0:
                batch.status = "completed"
            elif skipped_duplicates and not failed_files:
                batch.status = "completed"
            else:
                batch.status = "failed"
            batch.completed_at = datetime.utcnow()
            summary = {
                "failed_files": failed_files,
                "skipped_duplicates": skipped_duplicates,
            }
            if failed_files or skipped_duplicates:
                batch.result_summary = summary
            if skipped_duplicates:
                logger.info(
                    "OCR batch %s skipped %d duplicate file(s)",
                    batch_id,
                    len(skipped_duplicates),
                )
            db.commit()

    except Exception as e:
        logger.exception("OCR batch %s failed: %s", batch_id, e)
        batch = db.query(OCRBatch).filter(OCRBatch.id == batch_id).first()
        if batch:
            batch.status = "failed"
            batch.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
