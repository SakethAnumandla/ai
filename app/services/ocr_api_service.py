"""OCR HTTP orchestration — batch reload, legacy scan, bill preview."""
from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime
from io import BytesIO
from typing import List, Optional, Tuple

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Expense,
    ExpenseFile,
    ExpenseStatus,
    OCRBatch,
    OCRBill,
    TransactionType,
    UploadMethod,
    User,
)
from app.schemas import (
    BatchUploadResponse,
    BillDraftItem,
    BillPrefillData,
    MultiBillDraftResponse,
    OCRBatchStatusResponse,
    OCRBillResponse,
)
from app.services.ocr_batch_service import process_ocr_batch
from app.services.ocr_draft_service import (
    create_manual_upload_draft,
    create_ocr_draft,
    expense_needs_ocr_refresh,
    process_multi_file_drafts,
    to_multi_bill_response,
)
from app.services.ocr_service import OCRProcessor
from app.services.wallet_service import WalletService
from app.utils.category_hashtags import (
    get_hashtag_recommendations,
    normalize_hashtags_list,
    to_manual_category,
)
from app.utils.dedup import find_expense_by_file_hash
from app.utils.expense_helpers import (
    attach_files_to_expense,
    build_expense_response,
    parse_payment_method,
)
from app.utils.file_upload import process_multiple_files, process_single_file
from app.utils.ocr_categories import resolve_classification

_ocr_processor = OCRProcessor()


def build_ocr_description(data: dict) -> str:
    vendor = data.get("restaurant_name") or data.get("vendor_name") or "Bill"
    parts = [vendor]
    if data.get("ride_type"):
        parts.append(data["ride_type"])
    if data.get("bill_number"):
        parts.append(f"Invoice {data['bill_number']}")
    if data.get("ride_distance"):
        parts.append(f"{data['ride_distance']} km")
    if data.get("ride_duration"):
        parts.append(f"{data['ride_duration']} min")
    if data.get("pickup_location"):
        parts.append(f"From: {data['pickup_location'][:60]}")
    if data.get("dropoff_location"):
        parts.append(f"To: {data['dropoff_location'][:60]}")
    if data.get("customer_name"):
        parts.append(f"Customer: {data['customer_name']}")
    if data.get("table_number"):
        parts.append(f"Table #{data['table_number']}")
    if data.get("payment_method"):
        parts.append(f"Paid via {data['payment_method']}")
    if data.get("tax_amount"):
        parts.append(f"GST {data['tax_amount']}")
    tax_bd = data.get("tax_breakdown") or {}
    if tax_bd:
        parts.append("Tax: " + ", ".join(f"{k.upper()} {v}" for k, v in tax_bd.items()))
    items = data.get("items_list") or []
    if items:
        parts.append("Items: " + ", ".join(i.get("name", "") for i in items[:5]))
    return " | ".join(parts)


class OcrApiService:
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf", "webp"}

    def __init__(self, db: Session):
        self.db = db

    def validate_extensions(self, files: List[UploadFile]) -> None:
        for upload in files:
            ext = upload.filename.rsplit(".", 1)[-1].lower()
            if ext not in self.ALLOWED_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"Unsupported type: .{ext}")

    async def scan_drafts(
        self,
        user: User,
        files: List[UploadFile],
        *,
        force_rescan: bool,
    ) -> MultiBillDraftResponse:
        if not files:
            raise HTTPException(status_code=400, detail="At least one file is required")
        self.validate_extensions(files)
        file_infos = await process_multiple_files(files)
        for fi in file_infos:
            fi["is_primary"] = True
            fi["file_extension"] = fi["file_name"].rsplit(".", 1)[-1].lower()
        result = process_multi_file_drafts(
            self.db, user.id, file_infos, use_ocr=True, force_rescan=force_rescan
        )
        return to_multi_bill_response(result, self.db)

    def reload_batch_drafts(self, user: User, batch_id: int) -> MultiBillDraftResponse:
        batch = (
            self.db.query(OCRBatch)
            .filter(OCRBatch.id == batch_id, OCRBatch.user_id == user.id)
            .first()
        )
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        ocr_bills = (
            self.db.query(OCRBill)
            .filter(OCRBill.batch_id == batch_id)
            .order_by(OCRBill.id.asc())
            .all()
        )
        bills: List[BillDraftItem] = []
        for idx, ob in enumerate(ocr_bills, start=1):
            if not ob.expense_id:
                continue
            expense = (
                self.db.query(Expense)
                .options(joinedload(Expense.files))
                .filter(Expense.id == ob.expense_id, Expense.user_id == user.id)
                .first()
            )
            if not expense:
                continue
            file_name = ob.original_file_name or expense.file_name or f"file_{idx}"
            manual = to_manual_category(expense.main_category.value, expense.sub_category)
            recommended = get_hashtag_recommendations(manual, expense.sub_category)[
                "recommended"
            ]
            resp = build_expense_response(expense)
            bills.append(
                BillDraftItem(
                    bill_index=idx,
                    label=f"Bill {idx}",
                    expense_id=expense.id,
                    is_duplicate=False,
                    prefill=BillPrefillData(
                        bill_name=expense.bill_name,
                        bill_amount=expense.bill_amount,
                        bill_date=expense.bill_date,
                        transaction_type=expense.transaction_type.value,
                        main_category=expense.main_category.value,
                        manual_category=manual,
                        sub_category=expense.sub_category,
                        description=expense.description,
                        file_name=file_name,
                        amount_needs_review=expense.bill_amount <= 1.0
                        and expense.status.value == "draft",
                        vendor_name=expense.vendor_name,
                        bill_number=expense.bill_number,
                        payment_method=(
                            expense.payment_method.value if expense.payment_method else None
                        ),
                        hashtags=normalize_hashtags_list(expense.hashtags or recommended[:6]),
                        recommended_hashtags=recommended,
                    ),
                    files=resp.files,
                    preview_url=resp.preview_url,
                    thumbnail_url=resp.thumbnail_url,
                    can_preview=resp.can_preview,
                )
            )

        summary = batch.result_summary if isinstance(batch.result_summary, dict) else {}
        return MultiBillDraftResponse(
            batch_id=batch.id,
            bills=bills,
            failed=summary.get("failed_files", []),
            skipped_duplicates=summary.get("skipped_duplicates", []),
            message=f"{len(bills)} draft bill(s) in this batch",
        )

    async def scan_single(
        self,
        user: User,
        file: UploadFile,
        *,
        as_draft: bool,
        auto_approve: bool,
        force_rescan: bool,
    ):
        file_extension = file.filename.split(".")[-1].lower()
        if file_extension not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"File type not supported. Allowed: {sorted(self.ALLOWED_EXTENSIONS)}",
            )

        file_info = await process_single_file(file, is_primary=True)
        file_info["file_extension"] = file_extension
        file_hash = file_info.get("file_hash")
        if not force_rescan and file_hash:
            existing = find_expense_by_file_hash(self.db, user.id, file_hash)
            if existing and not expense_needs_ocr_refresh(existing):
                return build_expense_response(existing, is_duplicate=True)

        if as_draft:
            err: Optional[str] = None
            expense = None
            try:
                expense, _prefill, _dup, err = create_ocr_draft(
                    self.db, user.id, file_info, None, 1, force_rescan
                )
            except Exception as exc:
                from app.utils.ocr_quality import OcrScanUnreadable

                if isinstance(exc, OcrScanUnreadable):
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "ocr_unreadable",
                            "reason": exc.reason,
                            "message": exc.message,
                        },
                    ) from exc
                err = str(exc)
            if err or not expense:
                expense, _prefill, _dup = create_manual_upload_draft(
                    self.db, user.id, file_info, None, 1
                )
            self.db.commit()
            expense = (
                self.db.query(Expense)
                .options(joinedload(Expense.files))
                .filter(Expense.id == expense.id)
                .first()
            )
            return build_expense_response(expense)

        return await self._scan_single_legacy(
            user, file_info, file_extension, auto_approve=auto_approve
        )

    async def _scan_single_legacy(
        self, user: User, file_info: dict, file_extension: str, *, auto_approve: bool
    ):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_extension}") as tmp:
                tmp.write(file_info["file_data"])
                tmp_path = tmp.name

            extracted_data = await _ocr_processor.extract_bill_data(tmp_path, file_extension)
            if not extracted_data.get("total_amount"):
                raise HTTPException(status_code=400, detail="Could not extract bill amount from image")

            transaction_type, main_category, sub_category = resolve_classification(
                extracted_data, extracted_data.get("raw_text")
            )

            ocr_bill = OCRBill(
                user_id=user.id,
                original_file_data=file_info["file_data"],
                original_file_name=file_info["file_name"],
                original_file_size=file_info["file_size"],
                original_mime_type=file_info["mime_type"],
                bill_number=extracted_data.get("bill_number"),
                bill_date=extracted_data.get("bill_date"),
                vendor_name=extracted_data.get("vendor_name"),
                total_amount=extracted_data.get("total_amount"),
                tax_amount=extracted_data.get("tax_amount"),
                tax_breakdown=extracted_data.get("tax_breakdown") or None,
                ride_distance=extracted_data.get("ride_distance"),
                ride_duration=extracted_data.get("ride_duration"),
                ride_type=extracted_data.get("ride_type"),
                pickup_location=extracted_data.get("pickup_location"),
                dropoff_location=extracted_data.get("dropoff_location"),
                restaurant_name=extracted_data.get("restaurant_name"),
                items_list=extracted_data.get("items_list"),
                raw_text=extracted_data.get("raw_text"),
                confidence_score=extracted_data.get("confidence_score"),
                detected_main_category=main_category,
                detected_sub_category=sub_category,
            )
            self.db.add(ocr_bill)
            self.db.flush()

            vendor = (
                extracted_data.get("restaurant_name")
                or extracted_data.get("vendor_name")
                or "Unknown Vendor"
            )
            trip_label = extracted_data.get("ride_type") or "Trip"
            bill_suffix = extracted_data.get("bill_number") or (
                extracted_data.get("bill_date").strftime("%d %b %Y")
                if extracted_data.get("bill_date")
                else "OCR"
            )
            expense = Expense(
                user_id=user.id,
                bill_name=f"{vendor} — {trip_label} ({bill_suffix})",
                bill_amount=extracted_data["total_amount"],
                bill_date=extracted_data.get("bill_date") or datetime.utcnow(),
                transaction_type=transaction_type,
                main_category=main_category,
                sub_category=sub_category,
                description=build_ocr_description(extracted_data),
                vendor_name=extracted_data.get("vendor_name"),
                bill_number=extracted_data.get("bill_number"),
                tax_amount=extracted_data.get("tax_amount") or 0,
                payment_method=parse_payment_method(extracted_data.get("payment_method")),
                upload_method=UploadMethod.OCR,
                status=ExpenseStatus.APPROVED if auto_approve else ExpenseStatus.PENDING,
            )
            self.db.add(expense)
            self.db.flush()

            attach_files_to_expense(self.db, expense, [file_info])
            ocr_bill.expense_id = expense.id

            if auto_approve:
                expense.approved_at = datetime.utcnow()
                WalletService(self.db).update_wallet_balance(user.id, expense)

            self.db.commit()
            expense = (
                self.db.query(Expense)
                .options(joinedload(Expense.files))
                .filter(Expense.id == expense.id)
                .first()
            )
            return build_expense_response(expense)
        except HTTPException:
            raise
        except Exception as exc:
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"OCR processing failed: {exc}") from exc
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    async def scan_batch(
        self,
        user: User,
        files: List[UploadFile],
        *,
        as_draft: bool,
        auto_approve: bool,
        force_rescan: bool,
    ):
        if not files:
            raise HTTPException(status_code=400, detail="At least one file is required")

        if as_draft:
            self.validate_extensions(files)
            file_infos = await process_multiple_files(files)
            for fi in file_infos:
                fi["is_primary"] = True
                fi["file_extension"] = fi["file_name"].rsplit(".", 1)[-1].lower()
            result = process_multi_file_drafts(
                self.db, user.id, file_infos, use_ocr=True, force_rescan=force_rescan
            )
            return to_multi_bill_response(result, self.db)

        batch = OCRBatch(
            user_id=user.id,
            total_files=len(files),
            status="processing",
            batch_name=f"Batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)

        file_payloads = []
        for upload in files:
            content = await upload.read()
            ext = upload.filename.rsplit(".", 1)[-1].lower()
            mime = upload.content_type or "application/octet-stream"
            file_payloads.append(
                {
                    "filename": upload.filename,
                    "content": content,
                    "mime_type": mime,
                    "file_hash": hashlib.sha256(content).hexdigest(),
                }
            )

        return batch, file_payloads, BatchUploadResponse(
            batch_id=batch.id,
            total_files=batch.total_files,
            processed_files=0,
            status=batch.status,
            message=f"Processing {len(files)} files in background",
            status_url=f"/ocr/batch/{batch.id}/status",
        )

    def batch_status(self, user: User, batch_id: int) -> OCRBatchStatusResponse:
        batch = (
            self.db.query(OCRBatch)
            .filter(OCRBatch.id == batch_id, OCRBatch.user_id == user.id)
            .first()
        )
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        ocr_bills = self.db.query(OCRBill).filter(OCRBill.batch_id == batch_id).all()
        expense_ids = [b.expense_id for b in ocr_bills if b.expense_id]
        expenses = []
        if expense_ids:
            rows = (
                self.db.query(Expense)
                .options(joinedload(Expense.files))
                .filter(Expense.id.in_(expense_ids))
                .all()
            )
            expenses = [build_expense_response(e) for e in rows]

        summary = batch.result_summary if isinstance(batch.result_summary, dict) else {}
        return OCRBatchStatusResponse(
            batch_id=batch.id,
            status=batch.status,
            total_files=batch.total_files,
            processed_files=batch.processed_files,
            batch_name=batch.batch_name,
            created_at=batch.created_at,
            completed_at=batch.completed_at,
            expenses=expenses,
            failed_files=summary.get("failed_files", []),
            skipped_duplicates=summary.get("skipped_duplicates", []),
        )

    def list_bills(self, user_id: int) -> List[OCRBillResponse]:
        return self.db.query(OCRBill).filter(OCRBill.user_id == user_id).all()

    def get_bill(self, user_id: int, bill_id: int) -> OCRBill:
        bill = (
            self.db.query(OCRBill)
            .filter(OCRBill.id == bill_id, OCRBill.user_id == user_id)
            .first()
        )
        if not bill:
            raise HTTPException(status_code=404, detail="OCR bill not found")
        return bill

    def bill_file_stream(
        self, user_id: int, bill_id: int, *, download: bool
    ) -> Tuple[BytesIO, str, dict]:
        bill = self.get_bill(user_id, bill_id)
        if not bill.original_file_data:
            raise HTTPException(status_code=404, detail="File not found")
        mime = bill.original_mime_type or "application/octet-stream"
        if bill.expense_id and not download:
            ef = (
                self.db.query(ExpenseFile)
                .filter(ExpenseFile.expense_id == bill.expense_id)
                .order_by(ExpenseFile.is_primary.desc(), ExpenseFile.id.asc())
                .first()
            )
            if ef:
                mime = ef.mime_type
        disposition = "attachment" if download else "inline"
        name = bill.original_file_name or "bill"
        return (
            BytesIO(bill.original_file_data),
            mime,
            {"Content-Disposition": f'{disposition}; filename="{name}"'},
        )
