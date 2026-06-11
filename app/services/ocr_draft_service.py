"""Create draft expenses from OCR (one bill per file, minimal prefill)."""
import os
import re
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.models import (
    Expense,
    ExpenseStatus,
    MainCategory,
    OCRBatch,
    OCRBill,
    TransactionType,
    UploadMethod,
)
from app.services.ocr_service import OCRProcessor
from app.services.tax_service import TaxService
from app.utils.dedup import find_expense_by_file_hash
from app.utils.ocr_quality import OcrScanUnreadable
from app.utils.expense_helpers import attach_files_to_expense, parse_payment_method
from app.utils.category_hashtags import (
    normalize_hashtags_list,
    suggest_hashtags_from_ocr,
    to_manual_category,
)
from app.utils.ocr_categories import (
    default_bill_name,
    resolve_classification,
)

ocr_processor = OCRProcessor()


def coerce_bill_prefill(prefill: dict) -> dict:
    """Ensure prefill dict validates as BillPrefillData (avoid 500 on response build)."""
    from app.schemas import BillPrefillData

    data = dict(prefill)
    data.setdefault("file_name", "upload")
    data.setdefault("bill_name", "Bill upload")
    data.setdefault("bill_amount", 1.0)
    data.setdefault("bill_date", datetime.utcnow())
    data.setdefault("main_category", "miscellaneous")
    data.setdefault("transaction_type", "expense")
    try:
        return BillPrefillData.model_validate(data).model_dump()
    except Exception:
        data.pop("tax_summary", None)
        data["tax_lines"] = []
        return BillPrefillData.model_validate(data).model_dump()


def expense_needs_ocr_refresh(expense: Expense) -> bool:
    """Re-scan when OCR data on a duplicate is incomplete or placeholder."""
    amount = float(expense.bill_amount or 0)
    if amount <= 1.0:
        return True
    if amount > 50 and expense.subtotal is None:
        return True
    if amount > 50 and not expense.tax_lines:
        return True
    return False


def prefill_from_expense(expense: Expense, file_name: str) -> dict:
    return {
        "bill_name": expense.bill_name,
        "bill_amount": expense.bill_amount,
        "bill_date": expense.bill_date,
        "transaction_type": expense.transaction_type.value,
        "main_category": expense.main_category.value,
        "sub_category": expense.sub_category,
        "line_item": expense.line_item,
        "description": expense.description,
        "file_name": file_name,
        "amount_needs_review": float(expense.bill_amount or 0) <= 1.0,
        "vendor_name": expense.vendor_name,
        "restaurant_name": expense.vendor_name,
        "bill_number": expense.bill_number,
        "payment_method": (
            expense.payment_method.value if expense.payment_method else None
        ),
        "subtotal": expense.subtotal,
        "grand_total": expense.bill_amount,
        "tax_amount": expense.tax_amount,
        "amount_excl_gst": expense.amount_excl_gst,
        "gst_rate_pct": expense.gst_rate_pct,
        "gst_amount": expense.gst_amount,
        "financial_year": expense.financial_year,
        "currency_code": expense.currency_code or "EUR",
        "hashtags": list(expense.hashtags or []),
    }


def build_full_prefill_from_expense(
    db: Session, expense: Expense, file_name: str
) -> dict:
    """Rich prefill for duplicate scans — includes tax lines and taxonomy enrichment."""
    prefill = prefill_from_expense(expense, file_name)
    if expense.tax_lines:
        from app.services.tax_service import build_tax_summary, tax_lines_to_create_schema

        prefill["tax_summary"] = build_tax_summary(list(expense.tax_lines))
        prefill["tax_lines"] = tax_lines_to_create_schema(list(expense.tax_lines))
    from app.utils.ocr_prefill import enrich_prefill_dict

    return enrich_prefill_dict(prefill)


def apply_ocr_extract_to_expense(
    db: Session,
    expense: Expense,
    extracted: dict,
    prefill: dict,
) -> None:
    vendor = extracted.get("vendor_name") or extracted.get("restaurant_name")
    expense.bill_name = prefill["bill_name"]
    expense.bill_amount = prefill["bill_amount"]
    expense.bill_date = prefill["bill_date"]
    if vendor:
        expense.vendor_name = vendor
    if extracted.get("bill_number"):
        expense.bill_number = extracted.get("bill_number")
    if extracted.get("subtotal"):
        expense.subtotal = float(extracted["subtotal"])
    if extracted.get("tax_amount") is not None:
        expense.tax_amount = float(extracted["tax_amount"])
    pm = parse_payment_method(extracted.get("payment_method"))
    if pm:
        expense.payment_method = pm
    _, main_category, sub_category = resolve_classification(
        extracted, extracted.get("raw_text")
    )
    expense.main_category = main_category
    if sub_category:
        expense.sub_category = sub_category
    if prefill.get("hashtags"):
        expense.hashtags = normalize_hashtags_list(prefill["hashtags"])
    TaxService(db).import_from_ocr_breakdown(
        expense,
        extracted.get("tax_breakdown"),
        total_tax=extracted.get("tax_amount"),
    )


def _persist_ocr_bill(
    db: Session,
    user_id: int,
    file_info: dict,
    extracted: dict,
    batch_id: Optional[int],
    main_category: MainCategory,
    sub_category: Optional[str],
) -> OCRBill:
    ocr_bill = OCRBill(
        user_id=user_id,
        batch_id=batch_id,
        original_file_data=file_info["file_data"],
        original_file_name=file_info["file_name"],
        original_file_size=file_info["file_size"],
        original_mime_type=file_info["mime_type"],
        bill_number=extracted.get("bill_number"),
        bill_date=extracted.get("bill_date"),
        vendor_name=extracted.get("vendor_name"),
        vendor_gst=extracted.get("vendor_gst"),
        subtotal=extracted.get("subtotal"),
        total_amount=extracted.get("total_amount"),
        tax_amount=extracted.get("tax_amount"),
        tax_breakdown=extracted.get("tax_breakdown") or None,
        ride_distance=extracted.get("ride_distance"),
        ride_duration=extracted.get("ride_duration"),
        ride_type=extracted.get("ride_type"),
        pickup_location=extracted.get("pickup_location"),
        dropoff_location=extracted.get("dropoff_location"),
        restaurant_name=extracted.get("restaurant_name"),
        items_list=extracted.get("items_list"),
        payment_method=extracted.get("payment_method"),
        customer_name=extracted.get("customer_name"),
        raw_text=extracted.get("raw_text"),
        confidence_score=extracted.get("confidence_score"),
        detected_main_category=main_category,
        detected_sub_category=sub_category,
    )
    db.add(ocr_bill)
    db.flush()
    return ocr_bill


def _ocr_vendor_name(extracted: dict) -> Optional[str]:
    """Best merchant label for forms — prefer full venue name over logo word."""
    vendor = (extracted.get("vendor_name") or "").strip()
    restaurant = (extracted.get("restaurant_name") or "").strip()
    if vendor and restaurant:
        if vendor.lower() == restaurant.lower():
            return vendor
        if len(restaurant.split()) >= 2 and len(restaurant) >= len(vendor):
            return restaurant
        if len(vendor.split()) >= 2 and len(vendor) > len(restaurant):
            return vendor
        return f"{vendor} — {restaurant}"
    return vendor or restaurant or None


def _ocr_description_from_items(extracted: dict) -> Optional[str]:
    items = extracted.get("items_list") or []
    names: List[str] = []
    for row in items:
        if isinstance(row, dict):
            name = str(row.get("name") or "").strip()
            if name:
                names.append(name)
    if not names:
        return None
    if len(names) <= 3:
        return ", ".join(names)
    return ", ".join(names[:3]) + f" (+{len(names) - 3} more)"


def _frontend_payment_method(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = str(value).strip().lower()
    if key in ("cash", "upi"):
        return key
    if key in ("credit_card", "debit_card", "card"):
        return "card"
    if key in ("net_banking", "bank"):
        return "bank"
    if key == "wallet":
        return "upi"
    return key


def resolve_prefill_bill_amount(extracted: dict) -> tuple[float, bool]:
    """
    Pick the best bill total from OCR fields. Never default to a misleading €1 placeholder.
    Returns (amount, amount_needs_review).
    """
    tot = extracted.get("total_amount")
    sub = extracted.get("subtotal")
    tax = float(extracted.get("tax_amount") or 0)
    items = extracted.get("items_list") or []
    items_sum = (
        round(sum(float(i.get("price") or 0) for i in items), 2) if items else None
    )
    bill_no = extracted.get("bill_number")

    def _invoice_value() -> Optional[float]:
        if not bill_no:
            return None
        digits = re.sub(r"\D", "", str(bill_no))
        if not digits:
            return None
        try:
            return float(digits)
        except ValueError:
            return None

    inv_val = _invoice_value()

    def plausible_total(val: Optional[float]) -> bool:
        if val is None or val <= 0:
            return False
        if inv_val is not None and abs(val - inv_val) < 0.01:
            return False
        if val <= 1.5 and items_sum and items_sum > 50:
            return False
        return True

    def plausible_subtotal(val: Optional[float]) -> bool:
        if val is None or val <= 0:
            return False
        if val <= 1.5 and items_sum and items_sum > 50:
            return False
        return True

    candidates: list[tuple[float, int, bool]] = []
    if plausible_total(tot):
        candidates.append((float(tot), 100, False))
    if plausible_subtotal(sub) and tax > 0:
        candidates.append((round(float(sub) + tax, 2), 95, False))
    if items_sum and items_sum > 0:
        if tax > 0:
            candidates.append((round(items_sum + tax, 2), 90, False))
        candidates.append((float(items_sum), 75, True))
    if plausible_subtotal(sub):
        candidates.append((float(sub), 60, True))

    if candidates:
        candidates.sort(key=lambda x: (-x[1], -x[0]))
        return candidates[0][0], candidates[0][2]

    return 0.0, True


def build_prefill_dict(
    extracted: dict,
    file_name: str,
    bill_index: int,
    main_category: MainCategory,
    sub_category: Optional[str],
    transaction_type: TransactionType,
) -> dict:
    amount, needs_review = resolve_prefill_bill_amount(extracted)

    vendor = _ocr_vendor_name(extracted)
    pm = _frontend_payment_method(extracted.get("payment_method"))
    description = extracted.get("description") or _ocr_description_from_items(extracted)
    manual_category = to_manual_category(main_category.value, sub_category)
    recommended: List[str] = []
    if main_category != MainCategory.MISCELLANEOUS:
        recommended = suggest_hashtags_from_ocr(
            main_category.value,
            sub_category,
            vendor_name=extracted.get("vendor_name"),
            extracted=extracted,
        )
    return {
        "bill_name": default_bill_name(
            extracted, file_name, bill_index, transaction_type=transaction_type
        ),
        "bill_amount": float(amount),
        "bill_date": extracted.get("bill_date") or datetime.utcnow(),
        "transaction_type": transaction_type.value,
        "main_category": main_category.value,
        "manual_category": manual_category,
        "sub_category": sub_category,
        "description": description,
        "file_name": file_name,
        "amount_needs_review": needs_review,
        "vendor_name": vendor,
        "restaurant_name": extracted.get("restaurant_name") or vendor,
        "bill_number": extracted.get("bill_number"),
        "payment_method": pm,
        "subtotal": extracted.get("subtotal"),
        "grand_total": extracted.get("total_amount"),
        "tax_amount": extracted.get("tax_amount"),
        "hashtags": recommended[:3],
        "recommended_hashtags": recommended,
        "tax_summary": None,
        "items_list": extracted.get("items_list") or [],
        "raw_text": extracted.get("raw_text"),
        "scan_quality": extracted.get("scan_quality"),
        "retake_recommended": bool(extracted.get("retake_recommended")),
        "classification_confidence": extracted.get("classification_confidence"),
    }


def create_manual_upload_draft(
    db: Session,
    user_id: int,
    file_info: dict,
    batch_id: Optional[int],
    bill_index: int,
) -> Tuple[Expense, dict, bool]:
    """Draft from file only (no OCR)."""
    file_hash = file_info.get("file_hash")
    if file_hash:
        existing = find_expense_by_file_hash(db, user_id, file_hash)
        if existing:
            prefill = {
                "bill_name": existing.bill_name,
                "bill_amount": existing.bill_amount,
                "bill_date": existing.bill_date,
                "transaction_type": existing.transaction_type.value,
                "main_category": existing.main_category.value,
                "sub_category": existing.sub_category,
                "description": existing.description,
                "file_name": file_info["file_name"],
                "amount_needs_review": False,
                "vendor_name": existing.vendor_name,
                "bill_number": existing.bill_number,
                "payment_method": (
                    existing.payment_method.value if existing.payment_method else None
                ),
            }
            return existing, prefill, True

    main_category = MainCategory.MISCELLANEOUS
    manual_category = "shopping"
    recommended: List[str] = []
    prefill = {
        "bill_name": default_bill_name({}, file_info["file_name"], bill_index),
        "bill_amount": 1.0,
        "bill_date": datetime.utcnow(),
        "transaction_type": TransactionType.EXPENSE.value,
        "main_category": main_category.value,
        "manual_category": manual_category,
        "sub_category": None,
        "description": None,
        "file_name": file_info["file_name"],
        "amount_needs_review": True,
        "hashtags": recommended[:4],
        "recommended_hashtags": recommended,
    }

    expense = Expense(
        user_id=user_id,
        bill_name=prefill["bill_name"],
        bill_amount=prefill["bill_amount"],
        bill_date=prefill["bill_date"],
        transaction_type=TransactionType.EXPENSE,
        main_category=main_category,
        sub_category=None,
        description=None,
        tax_amount=0.0,
        discount_amount=0.0,
        upload_method=UploadMethod.MANUAL,
        status=ExpenseStatus.DRAFT,
        hashtags=normalize_hashtags_list(prefill.get("hashtags") or []),
    )
    db.add(expense)
    db.flush()
    attach_files_to_expense(db, expense, [file_info])
    ocr_bill = OCRBill(
        user_id=user_id,
        batch_id=batch_id,
        expense_id=expense.id,
        original_file_data=file_info["file_data"],
        original_file_name=file_info["file_name"],
        original_file_size=file_info["file_size"],
        original_mime_type=file_info["mime_type"],
        detected_main_category=main_category,
    )
    db.add(ocr_bill)
    db.flush()
    return expense, prefill, False


def create_ocr_draft(
    db: Session,
    user_id: int,
    file_info: dict,
    batch_id: Optional[int],
    bill_index: int,
    force_rescan: bool = False,
) -> Tuple[Optional[Expense], dict, bool, Optional[str]]:
    """
    Run OCR, store full data on OCRBill, create DRAFT expense with main fields only.
    Returns (expense, prefill_dict, is_duplicate, error_message).
    """
    file_hash = file_info.get("file_hash")
    refresh_expense: Optional[Expense] = None
    if file_hash:
        existing = find_expense_by_file_hash(db, user_id, file_hash)
        if existing:
            if force_rescan or expense_needs_ocr_refresh(existing):
                refresh_expense = existing
            else:
                return (
                    existing,
                    build_full_prefill_from_expense(
                        db, existing, file_info["file_name"]
                    ),
                    True,
                    None,
                )

    ext = file_info.get("file_extension") or file_info["file_name"].rsplit(".", 1)[-1].lower()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(file_info["file_data"])
            tmp_path = tmp.name

        extracted = ocr_processor.extract_bill_data_sync(tmp_path, ext)
        from app.utils.ocr_quality import ensure_ocr_readable

        ensure_ocr_readable(extracted)
    except OcrScanUnreadable:
        raise
    except Exception as e:
        return None, {}, False, str(e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    try:
        return _create_ocr_draft_from_extracted(
            db,
            user_id,
            file_info,
            extracted,
            batch_id,
            bill_index,
            refresh_expense,
        )
    except OcrScanUnreadable:
        raise
    except Exception as e:
        return None, {}, False, str(e)


def _create_ocr_draft_from_extracted(
    db: Session,
    user_id: int,
    file_info: dict,
    extracted: dict,
    batch_id: Optional[int],
    bill_index: int,
    refresh_expense: Optional[Expense],
) -> Tuple[Optional[Expense], dict, bool, Optional[str]]:
    transaction_type, main_category, sub_category = resolve_classification(
        extracted, extracted.get("raw_text")
    )
    prefill = build_prefill_dict(
        extracted,
        file_info["file_name"],
        bill_index,
        main_category,
        sub_category,
        transaction_type,
    )

    ocr_bill = _persist_ocr_bill(
        db, user_id, file_info, extracted, batch_id, main_category, sub_category
    )

    vendor = extracted.get("vendor_name") or extracted.get("restaurant_name")

    if refresh_expense is not None:
        apply_ocr_extract_to_expense(db, refresh_expense, extracted, prefill)
        ocr_bill.expense_id = refresh_expense.id
        prefill["hashtags"] = prefill.get("hashtags") or []
        prefill["recommended_hashtags"] = prefill.get("recommended_hashtags") or []
        prefill["expense_name"] = prefill["bill_name"]
        prefill["expense_amount"] = prefill["bill_amount"]
        prefill["expense_date"] = prefill["bill_date"]
        db.flush()
        db.refresh(refresh_expense)
        if refresh_expense.tax_lines:
            from app.services.tax_service import build_tax_summary, tax_lines_to_create_schema

            prefill["tax_summary"] = build_tax_summary(list(refresh_expense.tax_lines))
            prefill["tax_lines"] = tax_lines_to_create_schema(list(refresh_expense.tax_lines))
        prefill["subtotal"] = refresh_expense.subtotal
        prefill["tax_amount"] = refresh_expense.tax_amount
        from app.utils.ocr_prefill import enrich_prefill_dict

        prefill = enrich_prefill_dict(prefill)
        if prefill.get("category_needs_review"):
            refresh_expense.sub_category = None
            refresh_expense.line_item = None
        elif prefill.get("line_item"):
            refresh_expense.line_item = prefill["line_item"]
        if prefill.get("financial_year"):
            refresh_expense.financial_year = prefill["financial_year"]
        if prefill.get("amount_excl_gst") is not None:
            refresh_expense.amount_excl_gst = prefill["amount_excl_gst"]
        if prefill.get("gst_rate_pct") is not None:
            refresh_expense.gst_rate_pct = prefill["gst_rate_pct"]
        if prefill.get("gst_amount") is not None:
            refresh_expense.gst_amount = prefill["gst_amount"]
        if prefill.get("main_category"):
            try:
                from app.models import MainCategory as MC

                refresh_expense.main_category = MC(prefill["main_category"])
            except Exception:
                pass
        if prefill.get("sub_category"):
            refresh_expense.sub_category = prefill["sub_category"]
        return refresh_expense, prefill, True, None

    expense = Expense(
        user_id=user_id,
        bill_name=prefill["bill_name"],
        bill_amount=prefill["bill_amount"],
        bill_date=prefill["bill_date"],
        transaction_type=TransactionType.EXPENSE,
        main_category=main_category,
        sub_category=sub_category,
        description=None,
        vendor_name=vendor,
        bill_number=extracted.get("bill_number"),
        tax_amount=float(extracted.get("tax_amount") or 0.0),
        discount_amount=0.0,
        payment_method=parse_payment_method(extracted.get("payment_method")),
        upload_method=UploadMethod.OCR,
        status=ExpenseStatus.DRAFT,
        hashtags=normalize_hashtags_list(prefill.get("hashtags") or []),
    )
    db.add(expense)
    db.flush()
    attach_files_to_expense(db, expense, [file_info])
    ocr_bill.expense_id = expense.id

    if extracted.get("subtotal"):
        expense.subtotal = float(extracted["subtotal"])
    if extracted.get("tax_amount") is not None:
        expense.tax_amount = float(extracted["tax_amount"])
    TaxService(db).import_from_ocr_breakdown(
        expense,
        extracted.get("tax_breakdown"),
        total_tax=extracted.get("tax_amount"),
    )
    if expense.tax_lines:
        from app.services.tax_service import build_tax_summary, tax_lines_to_create_schema

        prefill["tax_summary"] = build_tax_summary(list(expense.tax_lines))
        prefill["tax_lines"] = tax_lines_to_create_schema(list(expense.tax_lines))
    prefill["hashtags"] = prefill.get("hashtags") or []
    prefill["recommended_hashtags"] = prefill.get("recommended_hashtags") or []
    prefill["expense_name"] = prefill["bill_name"]
    prefill["expense_amount"] = prefill["bill_amount"]
    prefill["expense_date"] = prefill["bill_date"]
    prefill["expense_number"] = prefill.get("bill_number")

    from app.utils.ocr_prefill import enrich_prefill_dict

    prefill = enrich_prefill_dict(prefill)
    if prefill.get("category_needs_review"):
        expense.sub_category = None
        expense.line_item = None
    elif prefill.get("line_item"):
        expense.line_item = prefill["line_item"]
    if prefill.get("financial_year"):
        expense.financial_year = prefill["financial_year"]
    if prefill.get("amount_excl_gst") is not None:
        expense.amount_excl_gst = prefill["amount_excl_gst"]
    if prefill.get("gst_rate_pct") is not None:
        expense.gst_rate_pct = prefill["gst_rate_pct"]
    if prefill.get("gst_amount") is not None:
        expense.gst_amount = prefill["gst_amount"]
    if prefill.get("itc_eligible") is not None:
        expense.itc_eligible = prefill["itc_eligible"]
    expense.currency_code = prefill.get("currency_code") or "EUR"
    if prefill.get("main_category"):
        try:
            from app.models import MainCategory as MC

            expense.main_category = MC(prefill["main_category"])
        except Exception:
            pass
    if prefill.get("sub_category"):
        expense.sub_category = prefill["sub_category"]

    return expense, prefill, False, None


def process_multi_file_drafts(
    db: Session,
    user_id: int,
    file_infos: List[dict],
    *,
    use_ocr: bool,
    force_rescan: bool = False,
    batch_name: Optional[str] = None,
) -> Dict[str, Any]:
    batch = OCRBatch(
        user_id=user_id,
        total_files=len(file_infos),
        processed_files=0,
        status="processing",
        batch_name=batch_name or f"Drafts_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
    )
    db.add(batch)
    db.flush()

    bills: List[dict] = []
    failed: List[dict] = []
    skipped: List[dict] = []

    for idx, file_info in enumerate(file_infos, start=1):
        try:
            if use_ocr:
                try:
                    expense, prefill, is_dup, err = create_ocr_draft(
                        db, user_id, file_info, batch.id, idx, force_rescan
                    )
                except OcrScanUnreadable:
                    expense, prefill, is_dup = create_manual_upload_draft(
                        db, user_id, file_info, batch.id, idx
                    )
                    err = None
            else:
                expense, prefill, is_dup = create_manual_upload_draft(
                    db, user_id, file_info, batch.id, idx
                )
                err = None

            if err or not expense:
                if not expense:
                    expense, prefill, is_dup = create_manual_upload_draft(
                        db, user_id, file_info, batch.id, idx
                    )
                    err = None
                if err:
                    failed.append(
                        {"bill_index": idx, "file_name": file_info["file_name"], "error": err}
                    )
                    continue

            if is_dup:
                skipped.append(
                    {
                        "bill_index": idx,
                        "file_name": file_info["file_name"],
                        "existing_expense_id": expense.id,
                    }
                )

            bills.append(
                {
                    "bill_index": idx,
                    "label": f"Bill {idx}",
                    "expense_id": expense.id,
                    "is_duplicate": is_dup,
                    "prefill": prefill,
                }
            )
            batch.processed_files += 1
        except Exception as e:
            failed.append(
                {"bill_index": idx, "file_name": file_info["file_name"], "error": str(e)}
            )

    batch.status = "completed" if bills else ("partial" if failed else "failed")
    batch.completed_at = datetime.utcnow()
    batch.result_summary = {"failed_files": failed, "skipped_duplicates": skipped}
    db.commit()

    return {
        "batch_id": batch.id,
        "bills": bills,
        "failed": failed,
        "skipped_duplicates": skipped,
    }


def to_multi_bill_response(result: dict, db: Optional[Session] = None):
    from app.schemas import BillDraftItem, BillPrefillData, MultiBillDraftResponse
    from app.utils.expense_helpers import build_expense_response

    bills = []
    for b in result["bills"]:
        files = []
        preview_url = None
        thumbnail_url = None
        can_preview = False
        if db:
            expense = (
                db.query(Expense)
                .options(joinedload(Expense.files))
                .filter(Expense.id == b["expense_id"])
                .first()
            )
            if expense:
                resp = build_expense_response(expense)
                files = resp.files
                preview_url = resp.preview_url
                thumbnail_url = resp.thumbnail_url
                can_preview = resp.can_preview
        bills.append(
            BillDraftItem(
                bill_index=b["bill_index"],
                label=b["label"],
                expense_id=b["expense_id"],
                is_duplicate=b["is_duplicate"],
                prefill=BillPrefillData(**coerce_bill_prefill(b["prefill"])),
                files=files,
                preview_url=preview_url,
                thumbnail_url=thumbnail_url,
                can_preview=can_preview,
            )
        )
    return MultiBillDraftResponse(
        batch_id=result["batch_id"],
        bills=bills,
        failed=result["failed"],
        skipped_duplicates=result["skipped_duplicates"],
        message=f"Created {len(bills)} draft expense(s). Review and submit when ready.",
    )
