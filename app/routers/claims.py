"""Policy claims — thin HTTP layer."""
import os
import tempfile
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import ClaimStatus, MainCategory, User
from app.schemas import ClaimResponse, ClaimSubmitResponse, ClaimSummary
from app.services.claim_response_service import build_claim_submit_response
from app.services.claim_service import ClaimService
from app.services.ocr_service import OCRProcessor
from app.services.policy_service import PolicyService
from app.utils.file_upload import process_uploaded_file
from app.utils.tax_form_parser import parse_tax_lines_form

router = APIRouter(prefix="/claims", tags=["claims"])
ocr_processor = OCRProcessor()


@router.post("/submit", response_model=ClaimSubmitResponse, status_code=status.HTTP_201_CREATED)
async def submit_claim(
    policy_id: int = Form(...),
    bill_name: str = Form(...),
    bill_amount: float = Form(...),
    bill_date: datetime = Form(...),
    main_category: Optional[str] = Form(None),
    sub_category: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    bill_number: Optional[str] = Form(None),
    vendor_name: Optional[str] = Form(None),
    payment_method: Optional[str] = Form(None),
    payment_mode: Optional[str] = Form(None),
    subtotal: Optional[float] = Form(None),
    tax_lines: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    policy = PolicyService(db).get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    file_data = await process_uploaded_file(file) if file else None
    expense_main = PolicyService.expense_category_for_policy(policy)
    if main_category:
        try:
            expense_main = MainCategory(main_category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid main_category: {main_category}") from exc

    try:
        parsed_taxes = parse_tax_lines_form(tax_lines) if tax_lines else []
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    claim_service = ClaimService(db)
    try:
        claim, meta = claim_service.submit_claim(
            user_id=current_user.id,
            policy=policy,
            bill_name=bill_name,
            bill_amount=bill_amount,
            bill_date=bill_date,
            main_category=expense_main,
            sub_category=sub_category or policy.sub_category,
            description=description,
            bill_number=bill_number,
            vendor_name=vendor_name,
            file_data=file_data["file_data"] if file_data else None,
            file_name=file_data["file_name"] if file_data else None,
            file_size=file_data["file_size"] if file_data else None,
            mime_type=file_data["mime_type"] if file_data else None,
            tax_lines=parsed_taxes or None,
            subtotal=subtotal,
            payment_method=payment_method or payment_mode,
        )
        db.commit()
        db.refresh(claim)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    claim = claim_service.require_claim(claim.id)
    return build_claim_submit_response(db, claim, meta)


@router.post("/scan-ocr", response_model=ClaimSubmitResponse, status_code=status.HTTP_201_CREATED)
async def scan_claim_ocr(
    policy_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    policy = PolicyService(db).get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    file_data = await process_uploaded_file(file)
    ext = file_data["file_name"].rsplit(".", 1)[-1].lower()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(file_data["file_data"])
            tmp_path = tmp.name
        extracted = ocr_processor.extract_bill_data_sync(tmp_path, ext)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    bill_amount = extracted.get("total_amount") or 0.0
    if bill_amount <= 0:
        raise HTTPException(status_code=400, detail="Could not extract bill amount from document")

    expense_main = PolicyService.expense_category_for_policy(policy)
    bill_name = extracted.get("vendor_name") or extracted.get("restaurant_name") or "Scanned bill"

    claim_service = ClaimService(db)
    try:
        claim, meta = claim_service.submit_claim(
            user_id=current_user.id,
            policy=policy,
            bill_name=bill_name,
            bill_amount=float(bill_amount),
            bill_date=extracted.get("bill_date") or datetime.utcnow(),
            main_category=expense_main,
            sub_category=extracted.get("sub_category") or policy.sub_category,
            description=extracted.get("description"),
            bill_number=extracted.get("bill_number"),
            vendor_name=extracted.get("vendor_name"),
            file_data=file_data["file_data"],
            file_name=file_data["file_name"],
            file_size=file_data["file_size"],
            mime_type=file_data["mime_type"],
            ocr_data=extracted,
            is_ocr_created=True,
            subtotal=extracted.get("subtotal"),
            payment_method=extracted.get("payment_method"),
        )
        db.commit()
        db.refresh(claim)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    claim = claim_service.require_claim(claim.id)
    return build_claim_submit_response(db, claim, meta)


@router.get("", response_model=List[ClaimResponse])
@router.get("/", response_model=List[ClaimResponse])
async def get_my_claims(
    status_filter: Optional[ClaimStatus] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    claims = ClaimService(db).list_user_claims(
        current_user.id, status_filter=status_filter, skip=skip, limit=limit
    )
    return [ClaimResponse.model_validate(c) for c in claims]


@router.get("/pending-approvals", response_model=List[ClaimResponse])
async def get_pending_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    claims = ClaimService(db).list_pending_for_approver(current_user.id)
    return [ClaimResponse.model_validate(c) for c in claims]


@router.get("/summary", response_model=ClaimSummary)
async def get_claim_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ClaimSummary(**ClaimService(db).get_claim_summary(current_user.id))


@router.get("/{claim_id}", response_model=ClaimResponse)
async def get_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        claim = ClaimService(db).get_claim_for_viewer(claim_id, current_user)
    except ValueError as exc:
        msg = str(exc)
        code = 403 if "Permission" in msg else 404
        raise HTTPException(status_code=code, detail=msg) from exc
    return ClaimResponse.model_validate(claim)
