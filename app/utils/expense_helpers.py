from typing import List, Optional

from app.data.business_taxonomy import resolve_line_item_meta
from app.models import Expense, ExpenseFile, OCRBill, PaymentMethod
from app.services.expense_approval_service import (
    approval_chain_for_expense,
    approval_remarks_for_expense,
    approval_stage_label,
    get_workflow_progress,
)


def submitted_by_display(expense: Expense) -> Optional[str]:
    name = (expense.submitted_by_name or "").strip()
    role = (expense.submitted_by_role or "").strip()
    if name and role:
        return f"{name} — {role}"
    if name:
        return name
    if role:
        return role
    return None
from app.utils.category_hashtags import (
    get_hashtag_recommendations,
    suggest_hashtags_from_ocr,
    to_manual_category,
)
from app.services.tax_service import build_tax_summary
from app.schemas import ExpenseTaxSummary, ExpenseTaxLineResponse
from app.schemas import (
    ExpenseDetailResponse,
    ExpenseFileResponse,
    ExpenseResponse,
    OCRBillDetailResponse,
)
from app.utils.expense_validation import approval_status_for, expense_is_editable


def can_preview_file(mime_type: Optional[str]) -> bool:
    if not mime_type:
        return False
    m = mime_type.lower()
    return m.startswith("image/") or m == "application/pdf"


def parse_payment_method(value: Optional[str]) -> Optional[PaymentMethod]:
    if not value:
        return None
    from app.utils.payment_modes import normalize_payment_mode

    normalized = normalize_payment_mode(value)
    if not normalized:
        return None
    try:
        return PaymentMethod(normalized)
    except ValueError:
        return None


def expense_file_to_response(expense_id: int, f: ExpenseFile) -> ExpenseFileResponse:
    file_url = f"/expenses/{expense_id}/files/{f.id}"
    preview = file_url if can_preview_file(f.mime_type) else None
    return ExpenseFileResponse(
        id=f.id,
        file_name=f.file_name,
        file_size=f.file_size,
        mime_type=f.mime_type,
        is_primary=f.is_primary,
        file_url=file_url,
        preview_url=preview,
        thumbnail_url=(
            f"/expenses/{expense_id}/files/{f.id}/thumbnail" if f.thumbnail_data else None
        ),
        can_preview=can_preview_file(f.mime_type),
        uploaded_at=f.uploaded_at,
    )


def build_tax_summary_response(expense: Expense) -> ExpenseTaxSummary:
    lines = list(expense.tax_lines or [])
    cc = expense.country_code or "IN"
    raw = build_tax_summary(lines, cc)
    total_tax = raw["total_tax"]
    subtotal = expense.subtotal
    if subtotal is None and expense.bill_amount and total_tax:
        subtotal = round(max(0, expense.bill_amount - total_tax), 2)
    raw["subtotal"] = subtotal
    line_rows = raw.pop("lines")
    return ExpenseTaxSummary(
        **raw,
        lines=[ExpenseTaxLineResponse(**row) for row in line_rows],
    )


def build_expense_response(
    expense: Expense, *, is_duplicate: bool = False
) -> ExpenseResponse:
    files: List[ExpenseFileResponse] = []
    if expense.files:
        files = [expense_file_to_response(expense.id, f) for f in expense.files]
    elif expense.file_data and expense.file_name:
        legacy_url = f"/expenses/{expense.id}/file"
        legacy_mime = expense.mime_type or "application/octet-stream"
        files = [
            ExpenseFileResponse(
                id=0,
                file_name=expense.file_name,
                file_size=expense.file_size or 0,
                mime_type=legacy_mime,
                is_primary=True,
                file_url=legacy_url,
                preview_url=legacy_url if can_preview_file(legacy_mime) else None,
                thumbnail_url=(
                    f"/expenses/{expense.id}/thumbnail" if expense.thumbnail_data else None
                ),
                can_preview=can_preview_file(legacy_mime),
                uploaded_at=expense.created_at,
            )
        ]

    primary = next((f for f in files if f.is_primary), files[0] if files else None)

    manual_cat = to_manual_category(
        expense.main_category.value, expense.sub_category
    )
    stored_tags = list(expense.hashtags or [])
    recommended = get_hashtag_recommendations(
        manual_cat, expense.sub_category
    )["recommended"]
    if not stored_tags and recommended:
        stored_tags = recommended[:5]

    preview_url = None
    can_preview = False
    if primary:
        preview_url = primary.preview_url or primary.file_url
        can_preview = primary.can_preview
    elif expense.file_data and expense.mime_type:
        legacy_url = f"/expenses/{expense.id}/file"
        can_preview = can_preview_file(expense.mime_type)
        preview_url = legacy_url if can_preview else None

    return ExpenseResponse(
        id=expense.id,
        user_id=expense.user_id,
        bill_name=expense.bill_name,
        bill_amount=expense.bill_amount,
        bill_date=expense.bill_date,
        transaction_type=expense.transaction_type,
        main_category=expense.main_category,
        sub_category=expense.sub_category,
        description=expense.description,
        payment_method=expense.payment_method.value if expense.payment_method else None,
        payment_mode=expense.payment_method.value if expense.payment_method else None,
        vendor_name=expense.vendor_name,
        bill_number=expense.bill_number,
        tax_amount=expense.tax_amount,
        discount_amount=expense.discount_amount,
        status=expense.status,
        upload_method=expense.upload_method.value,
        files=files,
        hashtags=stored_tags,
        recommended_hashtags=recommended,
        manual_category=manual_cat,
        rejection_reason=expense.rejection_reason,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
        approved_at=expense.approved_at,
        file_url=primary.file_url if primary else None,
        preview_url=preview_url,
        thumbnail_url=primary.thumbnail_url if primary else None,
        file_name=primary.file_name if primary else expense.file_name,
        file_size=primary.file_size if primary else expense.file_size,
        mime_type=primary.mime_type if primary else expense.mime_type,
        can_preview=can_preview,
        is_duplicate=is_duplicate,
        is_editable=expense_is_editable(expense),
        approval_status=approval_status_for(expense),
        approval_stage_label=approval_stage_label(expense),
        approval_chain=approval_chain_for_expense(expense),
        approval_progress=get_workflow_progress(expense),
        approval_remarks=approval_remarks_for_expense(expense),
        submitted_by_name=expense.submitted_by_name,
        submitted_by_role=expense.submitted_by_role,
        submitted_by_display=submitted_by_display(expense),
        line_item=expense.line_item,
        line_item_label=(
            resolve_line_item_meta(
                expense.main_category.value if expense.main_category else "",
                expense.sub_category,
                expense.line_item,
            )
            or {}
        ).get("label"),
        financial_year=expense.financial_year,
        amount_excl_gst=expense.amount_excl_gst,
        gst_rate_pct=expense.gst_rate_pct,
        gst_amount=expense.gst_amount,
        itc_eligible=expense.itc_eligible,
        currency_code=expense.currency_code or "EUR",
        country_code=expense.country_code or "IN",
        subtotal=expense.subtotal,
        tax_summary=(
            build_tax_summary_response(expense)
            if (expense.tax_lines or (expense.tax_amount or 0) > 0)
            else None
        ),
        expense_name=expense.bill_name,
        expense_amount=expense.bill_amount,
        expense_date=expense.bill_date,
        expense_number=expense.bill_number,
    )


def ocr_bill_to_detail(ocr_bill: OCRBill) -> OCRBillDetailResponse:
    return OCRBillDetailResponse(
        id=ocr_bill.id,
        bill_number=ocr_bill.bill_number,
        vendor_name=ocr_bill.vendor_name,
        vendor_gst=ocr_bill.vendor_gst,
        subtotal=ocr_bill.subtotal,
        total_amount=ocr_bill.total_amount,
        tax_amount=ocr_bill.tax_amount,
        tax_breakdown=ocr_bill.tax_breakdown,
        payment_method=ocr_bill.payment_method,
        ride_distance=ocr_bill.ride_distance,
        ride_duration=ocr_bill.ride_duration,
        ride_type=ocr_bill.ride_type,
        pickup_location=ocr_bill.pickup_location,
        dropoff_location=ocr_bill.dropoff_location,
        restaurant_name=ocr_bill.restaurant_name,
        items_list=ocr_bill.items_list,
        customer_name=ocr_bill.customer_name,
        confidence_score=ocr_bill.confidence_score,
    )


def build_expense_detail_response(
    expense: Expense, ocr_bill: Optional[OCRBill] = None
) -> ExpenseDetailResponse:
    base = build_expense_response(expense)
    remarks = approval_remarks_for_expense(expense)
    # Exclude approval_remarks from the dump — passing it twice causes a 500 in production.
    payload = base.model_dump(exclude={"approval_remarks"})
    return ExpenseDetailResponse(
        **payload,
        approval_remarks=remarks,
        remarks_table=remarks,
        ocr_details=ocr_bill_to_detail(ocr_bill) if ocr_bill else None,
    )


def attach_files_to_expense(db, expense: Expense, processed_files: List[dict]) -> None:
    """Persist ExpenseFile rows and legacy primary columns on expense."""
    for file_data in processed_files:
        db.add(
            ExpenseFile(
                expense_id=expense.id,
                file_data=file_data["file_data"],
                file_name=file_data["file_name"],
                file_size=file_data["file_size"],
                mime_type=file_data["mime_type"],
                file_hash=file_data.get("file_hash"),
                thumbnail_data=file_data.get("thumbnail_data"),
                is_primary=file_data.get("is_primary", False),
            )
        )

    primary = next((f for f in processed_files if f.get("is_primary")), None)
    if not primary and processed_files:
        primary = processed_files[0]
    if primary:
        expense.file_data = primary["file_data"]
        expense.file_name = primary["file_name"]
        expense.file_size = primary["file_size"]
        expense.mime_type = primary["mime_type"]
        expense.file_hash = primary.get("file_hash")
        expense.thumbnail_data = primary.get("thumbnail_data")
