# Expense HTTP routes — thin layer; logic in services.

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.data.business_taxonomy import APPROVER_DIRECTORY
from app.database import get_db
from app.dependencies import ExpenseFilters, PaginationParams, get_current_user, get_default_user
from app.domain.workflow_schemas import ExpenseApprovalAction
from app.models import ExpenseStatus, MainCategory, TransactionType, User
from app.services.expense_approval_service import (
    build_expense_approval_remarks_payload,
    build_expense_approval_workflow_payload,
    build_pending_expense_approval_queue,
    get_expense_for_viewer,
    process_expense_approval,
)
from app.schemas import (
    BillDraftItem,
    ExpenseApproval,
    ExpenseApprovalRemarksResponse,
    ExpenseDetailResponse,
    ExpenseFileResponse,
    ExpenseResponse,
    ExpenseSubmit,
    ExpenseTaxesReplaceRequest,
    ExpenseTaxSummary,
    ExpenseUpdate,
    MultiBillDraftResponse,
)
from app.services.expense_access_service import ExpenseAccessService
from app.services.expense_file_service import ExpenseFileService
from app.services.expense_service import ExpenseService
from app.services.manual_expense_service import ManualExpenseForm, ManualExpenseService
from app.services.ocr_draft_service import process_multi_file_drafts, to_multi_bill_response
from app.services.tax_service import TaxService
from app.utils.expense_helpers import build_expense_detail_response, build_expense_response, build_tax_summary_response
from app.utils.file_upload import process_multiple_files

router = APIRouter(prefix="/expenses", tags=["expenses"])


# ── Expense approval workflow (duplicate paths for older deployments) ──────────


@router.get("/approvers/directory")
async def expense_approver_directory():
    return {"approvers": APPROVER_DIRECTORY}


@router.get("/approvals/pending")
async def pending_expense_approvals(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return build_pending_expense_approval_queue(db, user.id)


@router.get("/{expense_id}/approval-workflow")
async def expense_approval_workflow(
    expense_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    expense = get_expense_for_viewer(db, expense_id, user)
    if not expense:
        raise HTTPException(404, "Expense not found")
    return build_expense_approval_workflow_payload(expense)


@router.post("/approvals/{approval_id}/action")
async def expense_approval_action(
    approval_id: int,
    body: ExpenseApprovalAction,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        expense = process_expense_approval(
            db,
            approval_id=approval_id,
            user=user,
            action=body.action,
            comments=body.resolved_remarks(),
        )
        db.commit()
        db.refresh(expense)
        return build_expense_response(expense)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/manual/scan", response_model=BillDraftItem, status_code=status.HTTP_201_CREATED)
async def scan_manual_expense(
    file: UploadFile = File(..., description="Receipt/bill image or PDF — OCR prefills the form"),
    force_duplicate: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    return await ManualExpenseService(db).scan_manual_prefill(
        current_user, file, force_duplicate=force_duplicate
    )


@router.post("/manual", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
async def create_manual_expense(
    bill_name: str = Form(...),
    bill_amount: float = Form(...),
    bill_date: str = Form(...),
    main_category: MainCategory = Form(...),
    sub_category: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    payment_method: Optional[str] = Form(None),
    payment_mode: Optional[str] = Form(None),
    vendor_name: Optional[str] = Form(None),
    line_item: Optional[str] = Form(None),
    amount_excl_gst: Optional[float] = Form(None),
    gst_rate_pct: Optional[float] = Form(None),
    gst_amount: Optional[float] = Form(None),
    currency_code: Optional[str] = Form(None),
    bill_number: Optional[str] = Form(None),
    tax_amount: Optional[float] = Form(0.0),
    discount_amount: Optional[float] = Form(0.0),
    files: List[UploadFile] = File(default=[]),
    hashtags: Optional[str] = Form(None),
    subtotal: Optional[float] = Form(None),
    tax_lines: Optional[str] = Form(None),
    save_as_draft: bool = Form(False),
    confirm_submit: bool = Form(False),
    submitted_by_name: Optional[str] = Form(None),
    submitted_by_role: Optional[str] = Form(None),
    force_duplicate: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    form = ManualExpenseForm(
        bill_name=bill_name,
        bill_amount=bill_amount,
        bill_date=bill_date,
        main_category=main_category,
        sub_category=sub_category,
        description=description,
        payment_method=payment_method,
        payment_mode=payment_mode,
        vendor_name=vendor_name,
        line_item=line_item,
        amount_excl_gst=amount_excl_gst,
        gst_rate_pct=gst_rate_pct,
        gst_amount=gst_amount,
        currency_code=currency_code,
        bill_number=bill_number,
        tax_amount=tax_amount or 0.0,
        discount_amount=discount_amount or 0.0,
        hashtags=hashtags,
        subtotal=subtotal,
        tax_lines=tax_lines,
        save_as_draft=save_as_draft,
        confirm_submit=confirm_submit,
        submitted_by_name=submitted_by_name,
        submitted_by_role=submitted_by_role,
        force_duplicate=force_duplicate,
    )
    return await ManualExpenseService(db).create_manual(current_user, form, files)


@router.post("/upload-drafts", response_model=MultiBillDraftResponse)
async def upload_files_as_drafts(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")
    file_infos = await process_multiple_files(files)
    for fi in file_infos:
        fi["is_primary"] = True
        fi["file_extension"] = fi["file_name"].rsplit(".", 1)[-1].lower()
    result = process_multi_file_drafts(db, current_user.id, file_infos, use_ocr=False)
    return to_multi_bill_response(result, db)


@router.get("/drafts", response_model=List[ExpenseResponse])
async def list_draft_expenses(
    batch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    return ManualExpenseService(db).list_drafts(current_user.id, batch_id=batch_id)


@router.get("/{expense_id}/taxes", response_model=ExpenseTaxSummary)
async def get_expense_taxes(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    expense = ExpenseAccessService(db).get_for_viewer(expense_id, current_user.id)
    return build_tax_summary_response(expense)


@router.put("/{expense_id}/taxes", response_model=ExpenseTaxSummary)
async def replace_expense_taxes(
    expense_id: int,
    body: ExpenseTaxesReplaceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    expense = ExpenseAccessService(db).get_for_viewer(expense_id, current_user.id)
    if expense.status == ExpenseStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Cannot edit taxes on approved expense")
    if expense.status in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
        raise HTTPException(status_code=400, detail="Cannot edit taxes on submitted expense")
    TaxService(db).replace_expense_taxes(expense, [line.model_dump() for line in body.tax_lines])
    db.commit()
    db.refresh(expense)
    expense = ExpenseAccessService(db).get_for_viewer(expense_id, current_user.id)
    return build_tax_summary_response(expense)


@router.get("/{expense_id}/approval-remarks", response_model=ExpenseApprovalRemarksResponse)
async def get_expense_approval_remarks(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    """Approver remarks table for bill details (L1/L2/L3 after approve or reject)."""
    expense = ExpenseAccessService(db).get_for_viewer(expense_id, current_user.id)
    return build_expense_approval_remarks_payload(expense)


@router.get("/{expense_id}/details", response_model=ExpenseDetailResponse)
async def get_expense_with_ocr_details(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    access = ExpenseAccessService(db)
    expense = access.get_for_viewer(expense_id, current_user.id)
    ocr_bill = access.get_ocr_bill(expense_id, expense.user_id)
    return build_expense_detail_response(expense, ocr_bill)


@router.post("/{expense_id}/submit", response_model=ExpenseResponse)
async def submit_draft_expense(
    expense_id: int,
    body: ExpenseSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    expense = ExpenseService(db).submit_draft(expense_id, current_user.id, body)
    return build_expense_response(
        ExpenseAccessService(db).get_for_viewer(expense.id, current_user.id)
    )


@router.post("/{expense_id}/resubmit", response_model=ExpenseResponse)
async def resubmit_rejected_expense(
    expense_id: int,
    body: ExpenseSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    expense = ExpenseAccessService(db).get_for_viewer(expense_id, current_user.id)
    if expense.status != ExpenseStatus.REJECTED:
        raise HTTPException(status_code=400, detail="Only rejected expenses can be resubmitted")
    submit_data = body.model_copy(update={"confirm_submit": True, "save_as_draft": False})
    expense = ExpenseService(db).submit_draft(expense_id, current_user.id, submit_data)
    return build_expense_response(
        ExpenseAccessService(db).get_for_viewer(expense.id, current_user.id)
    )


@router.post("/{expense_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
async def discard_incomplete_draft(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    ExpenseService(db).discard_incomplete_draft(expense_id, current_user.id)
    return None


@router.get("", response_model=List[ExpenseResponse])
async def list_expenses(
    pagination: PaginationParams = Depends(),
    filters: ExpenseFilters = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    expenses, _ = ExpenseService(db).get_user_expenses(
        user_id=current_user.id,
        status=filters.status,
        statuses=filters.statuses,
        main_category=filters.main_category,
        sub_category=filters.sub_category,
        transaction_type=filters.transaction_type or TransactionType.EXPENSE,
        start_date=filters.start_date,
        end_date=filters.end_date,
        search_term=filters.search,
        min_amount=filters.min_amount,
        max_amount=filters.max_amount,
        upload_method=filters.upload_method,
        hashtag=filters.hashtag,
        skip=pagination.skip,
        limit=pagination.limit,
    )
    return [build_expense_response(e) for e in expenses]


@router.get("/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    return build_expense_response(
        ExpenseAccessService(db).get_for_viewer(expense_id, current_user.id)
    )


@router.patch("/{expense_id}", response_model=ExpenseResponse)
async def update_expense(
    expense_id: int,
    body: ExpenseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    expense = ExpenseService(db).update_expense(expense_id, current_user.id, body)
    return build_expense_response(
        ExpenseAccessService(db).get_for_viewer(expense.id, current_user.id)
    )


@router.post("/{expense_id}/approve", response_model=ExpenseResponse)
async def approve_expense(
    expense_id: int,
    body: ExpenseApproval,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    from app.services.expense_approval_service import approve_expense_current_step

    expense = ExpenseAccessService(db).get_for_viewer(expense_id, current_user.id)
    if expense.approval_steps:
        action = "approve" if body.status == ExpenseStatus.APPROVED else "reject"
        try:
            expense = approve_expense_current_step(
                db,
                expense,
                action=action,
                comments=body.comments or body.rejection_reason,
                user=current_user,
            )
            db.commit()
            db.refresh(expense)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        expense = ExpenseService(db).update_expense_status(
            expense_id,
            current_user.id,
            body.status,
            rejection_reason=body.rejection_reason,
        )
    return build_expense_response(
        ExpenseAccessService(db).get_for_viewer(expense.id, current_user.id)
    )


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    ExpenseService(db).delete_expense(expense_id, current_user.id)
    return None


@router.post("/{expense_id}/files", response_model=List[ExpenseFileResponse])
async def add_files_to_expense(
    expense_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    return await ExpenseFileService(db).add_files(expense_id, current_user.id, files)


@router.get("/{expense_id}/files", response_model=List[ExpenseFileResponse])
async def get_expense_files(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    return ExpenseFileService(db).list_files(expense_id, current_user.id)


@router.get("/{expense_id}/files/{file_id}")
async def download_expense_file_by_id(
    expense_id: int,
    file_id: int,
    download: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    body, mime, headers = ExpenseFileService(db).file_stream(
        expense_id, file_id, current_user.id, download=download
    )
    return StreamingResponse(body, media_type=mime, headers=headers)


@router.get("/{expense_id}/files/{file_id}/thumbnail")
async def get_expense_file_thumbnail(
    expense_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    body, mime, headers = ExpenseFileService(db).thumbnail_stream(
        expense_id, file_id, current_user.id
    )
    return StreamingResponse(body, media_type=mime, headers=headers)


@router.delete("/{expense_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense_file(
    expense_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    ExpenseFileService(db).delete_file(expense_id, file_id, current_user.id)
    return None


@router.get("/{expense_id}/file")
async def download_expense_file_legacy(
    expense_id: int,
    download: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    body, _name, mime, headers = ExpenseFileService(db).legacy_file_stream(
        expense_id, current_user.id, download=download
    )
    return StreamingResponse(body, media_type=mime, headers=headers)


@router.get("/{expense_id}/thumbnail")
async def get_expense_thumbnail_legacy(
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_default_user),
):
    body, mime, headers = ExpenseFileService(db).legacy_thumbnail_stream(
        expense_id, current_user.id
    )
    return StreamingResponse(body, media_type=mime, headers=headers)
