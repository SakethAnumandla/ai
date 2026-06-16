"""Manual expense creation and OCR prefill scan."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.data.business_taxonomy import normalize_taxonomy_fields, suggest_categories_from_text
from app.models import Expense, ExpenseStatus, MainCategory, OCRBill, UploadMethod, User
from app.schemas import BillDraftItem, BillPrefillData, ExpenseResponse
from app.services.expense_access_service import ExpenseAccessService
from app.services.expense_approval_service import create_expense_approval_workflow
from app.services.expense_service import ExpenseService
from app.services.wallet_service import WalletService
from app.services.ocr_draft_service import (
    build_full_prefill_from_expense,
    coerce_bill_prefill,
    create_manual_upload_draft,
    create_ocr_draft,
)
from app.services.tax_service import TaxService
from app.utils.category_hashtags import (
    get_hashtag_recommendations,
    normalize_hashtags_list,
    parse_hashtags_input,
    to_manual_category,
)
from app.utils.date_parser import parse_bill_date
from app.utils.ocr_quality import OcrScanUnreadable
from app.utils.dedup import find_expense_by_file_hash
from app.utils.expense_business_fields import apply_business_fields
from app.utils.expense_helpers import attach_files_to_expense, build_expense_response
from app.utils.expense_validation import (
    force_expense_transaction_type,
    validate_required_draft_fields,
)
from app.utils.file_upload import process_multiple_files, process_single_file
from app.utils.tax_form_parser import parse_tax_lines_form
from app.utils.async_io import run_blocking


@dataclass
class ManualExpenseForm:
    bill_name: str
    bill_amount: float
    bill_date: str
    main_category: MainCategory
    sub_category: Optional[str] = None
    description: Optional[str] = None
    payment_method: Optional[str] = None
    payment_mode: Optional[str] = None
    vendor_name: Optional[str] = None
    line_item: Optional[str] = None
    amount_excl_gst: Optional[float] = None
    gst_rate_pct: Optional[float] = None
    gst_amount: Optional[float] = None
    currency_code: Optional[str] = None
    bill_number: Optional[str] = None
    tax_amount: float = 0.0
    discount_amount: float = 0.0
    hashtags: Optional[str] = None
    subtotal: Optional[float] = None
    tax_lines: Optional[str] = None
    save_as_draft: bool = False
    confirm_submit: bool = False
    submitted_by_name: Optional[str] = None
    submitted_by_role: Optional[str] = None
    force_duplicate: bool = False


class ManualExpenseService:
    def __init__(self, db: Session):
        self.db = db
        self.access = ExpenseAccessService(db)

    def _resolve_status(self, form: ManualExpenseForm) -> ExpenseStatus:
        if form.save_as_draft:
            validate_required_draft_fields(
                bill_name=form.bill_name,
                bill_amount=form.bill_amount,
                main_category=form.main_category,
            )
            return ExpenseStatus.DRAFT
        if form.confirm_submit:
            validate_required_draft_fields(
                bill_name=form.bill_name,
                bill_amount=form.bill_amount,
                main_category=form.main_category,
            )
            if settings.expense_self_auto_approve_enabled:
                return ExpenseStatus.APPROVED
            return ExpenseStatus.SUBMITTED
        raise HTTPException(
            status_code=400,
            detail="Set save_as_draft=true to save as draft, or confirm_submit=true to submit for approval.",
        )

    async def create_manual(
        self, user: User, form: ManualExpenseForm, files: List[UploadFile]
    ) -> ExpenseResponse:
        expense_status = self._resolve_status(form)
        if form.bill_amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be greater than 0")

        processed_files = await process_multiple_files(files)
        if not form.force_duplicate and processed_files:
            for pf in processed_files:
                file_hash = pf.get("file_hash")
                if not file_hash:
                    continue
                existing = find_expense_by_file_hash(self.db, user.id, file_hash)
                if existing:
                    return build_expense_response(existing, is_duplicate=True)

        parsed_date = parse_bill_date(form.bill_date)
        taxonomy = normalize_taxonomy_fields(
            form.main_category.value,
            form.sub_category,
            form.line_item,
        )
        main_value = taxonomy["main_category"] or form.main_category.value
        try:
            resolved_main = MainCategory(main_value)
        except ValueError:
            resolved_main = form.main_category
        resolved_sub = taxonomy["sub_category"]
        resolved_line_item = taxonomy["line_item"]

        tag_list = normalize_hashtags_list(parse_hashtags_input(form.hashtags))
        if not tag_list:
            manual = to_manual_category(resolved_main.value, resolved_sub)
            if manual != "miscellaneous":
                tag_list = normalize_hashtags_list(
                    get_hashtag_recommendations(manual, resolved_sub)["recommended"][:3]
                )

        from app.utils.expense_helpers import parse_payment_method

        expense = Expense(
            user_id=user.id,
            company_id=getattr(user, "company_id", 1),
            bill_name=form.bill_name,
            bill_amount=form.bill_amount,
            bill_date=parsed_date,
            transaction_type=force_expense_transaction_type(),
            main_category=resolved_main,
            sub_category=resolved_sub,
            description=form.description,
            payment_method=parse_payment_method(form.payment_method or form.payment_mode),
            vendor_name=form.vendor_name,
            bill_number=form.bill_number,
            tax_amount=form.tax_amount or 0.0,
            discount_amount=form.discount_amount or 0.0,
            upload_method=UploadMethod.MANUAL,
            status=expense_status,
            hashtags=tag_list,
            subtotal=form.subtotal,
            submitted_by_name=(form.submitted_by_name or "").strip() or None,
            submitted_by_role=(form.submitted_by_role or "").strip() or None,
        )

        hints = suggest_categories_from_text(
            f"{form.vendor_name or ''} {form.bill_name or ''} {form.description or ''}"
        )
        apply_business_fields(
            expense,
            main_category=resolved_main,
            sub_category=resolved_sub or hints.get("sub_category"),
            line_item=resolved_line_item or hints.get("line_item"),
            bill_date=parsed_date,
            amount_excl_gst=form.amount_excl_gst,
            gst_rate_pct=form.gst_rate_pct,
            gst_amount=form.gst_amount,
            currency_code=form.currency_code or "EUR",
            vendor_name=form.vendor_name,
        )

        self.db.add(expense)
        self.db.flush()

        if processed_files:
            attach_files_to_expense(self.db, expense, processed_files)

        try:
            parsed_taxes = parse_tax_lines_form(form.tax_lines)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if parsed_taxes:
            TaxService(self.db).replace_expense_taxes(expense, parsed_taxes)
        elif form.tax_amount and form.tax_amount > 0:
            TaxService(self.db).import_from_ocr_breakdown(expense, None, total_tax=form.tax_amount)

        if expense_status == ExpenseStatus.SUBMITTED:
            create_expense_approval_workflow(self.db, expense)
        elif expense_status == ExpenseStatus.APPROVED:
            expense.approved_at = datetime.now(timezone.utc)
            WalletService(self.db).update_wallet_balance(user.id, expense)

        self.db.commit()
        self.db.refresh(expense)
        expense = self.access.get_for_viewer(expense.id, user.id)
        return build_expense_response(expense)

    async def scan_manual_prefill(
        self, user: User, file: UploadFile, *, force_duplicate: bool
    ) -> BillDraftItem:
        processed = await process_single_file(file)
        processed["is_primary"] = True
        processed["file_extension"] = processed["file_name"].rsplit(".", 1)[-1].lower()

        if not force_duplicate and processed.get("file_hash"):
            existing = find_expense_by_file_hash(self.db, user.id, processed["file_hash"])
            if existing:
                resp = build_expense_response(existing, is_duplicate=True)
                prefill = build_full_prefill_from_expense(
                    self.db, existing, processed["file_name"]
                )
                return BillDraftItem(
                    bill_index=1,
                    label="Expense 1",
                    expense_id=existing.id,
                    is_duplicate=True,
                    prefill=BillPrefillData(**coerce_bill_prefill(prefill)),
                    files=resp.files,
                    preview_url=resp.preview_url,
                    thumbnail_url=resp.thumbnail_url,
                    can_preview=resp.can_preview,
                )

        try:
            expense, prefill, is_dup, err = await run_blocking(
                create_ocr_draft,
                self.db,
                user.id,
                processed,
                None,
                1,
                force_rescan=force_duplicate,
            )
        except OcrScanUnreadable as unreadable:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ocr_unreadable",
                    "reason": unreadable.reason,
                    "message": unreadable.message,
                },
            ) from unreadable
        if err or not expense:
            expense, prefill, is_dup = await run_blocking(
                create_manual_upload_draft,
                self.db,
                user.id,
                processed,
                None,
                1,
            )

        self.db.commit()
        expense = self.access.get_for_viewer(expense.id, user.id)
        resp = build_expense_response(expense)
        return BillDraftItem(
            bill_index=1,
            label="Expense 1",
            expense_id=expense.id,
            is_duplicate=is_dup,
            prefill=BillPrefillData(**coerce_bill_prefill(prefill)),
            files=resp.files,
            preview_url=resp.preview_url,
            thumbnail_url=resp.thumbnail_url,
            can_preview=resp.can_preview,
        )

    def list_drafts(
        self,
        user_id: int,
        batch_id: Optional[int] = None,
        company_id: int = 1,
    ) -> List[ExpenseResponse]:
        if batch_id is not None:
            expense_ids = [
                row[0]
                for row in self.db.query(OCRBill.expense_id)
                .filter(
                    OCRBill.batch_id == batch_id,
                    OCRBill.user_id == user_id,
                    OCRBill.company_id == company_id,
                    OCRBill.expense_id.isnot(None),
                )
                .all()
            ]
            if not expense_ids:
                return []
            rows = (
                self.db.query(Expense)
                .options(joinedload(Expense.files))
                .filter(
                    Expense.id.in_(expense_ids),
                    Expense.user_id == user_id,
                    Expense.company_id == company_id,
                    Expense.status == ExpenseStatus.DRAFT,
                )
                .order_by(Expense.id.asc())
                .all()
            )
            return [build_expense_response(e) for e in rows]

        rows = ExpenseService(self.db).get_draft_expenses(user_id, company_id=company_id)
        return [build_expense_response(e) for e in rows]
