# OCR HTTP routes — thin layer; logic in OcrApiService / ocr_draft_service.

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.scope import ExpenseScope, ScopedActor, get_expense_scope
from app.schemas import (
    BatchUploadResponse,
    ExpenseResponse,
    MultiBillDraftResponse,
    OCRBatchStatusResponse,
    OCRBillResponse,
)
from app.services.ocr_api_service import OcrApiService
from app.services.ocr_batch_service import process_ocr_batch

router = APIRouter(prefix="/ocr", tags=["ocr"])


def _actor(scope: ExpenseScope) -> ScopedActor:
    return ScopedActor.from_scope(scope)


@router.post("/scan-drafts", response_model=MultiBillDraftResponse)
async def scan_multiple_as_drafts(
    files: List[UploadFile] = File(...),
    force_rescan: bool = Query(False),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    return await OcrApiService(db).scan_drafts(
        _actor(scope), files, force_rescan=force_rescan
    )


@router.get("/batch/{batch_id}/drafts", response_model=MultiBillDraftResponse)
async def get_batch_drafts(
    batch_id: int,
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    return OcrApiService(db).reload_batch_drafts(_actor(scope), batch_id)


@router.post("/scan", response_model=ExpenseResponse)
async def scan_single_bill(
    file: UploadFile = File(...),
    as_draft: bool = Query(True),
    auto_approve: bool = False,
    force_rescan: bool = Query(False),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    actor = _actor(scope)
    return await OcrApiService(db).scan_single(
        actor,
        file,
        as_draft=as_draft,
        auto_approve=auto_approve,
        force_rescan=force_rescan,
    )


@router.post("/scan-batch")
async def scan_multiple_bills(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    as_draft: bool = Query(False),
    auto_approve: bool = False,
    force_rescan: bool = Query(False),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    actor = _actor(scope)
    result = await OcrApiService(db).scan_batch(
        actor,
        files,
        as_draft=as_draft,
        auto_approve=auto_approve,
        force_rescan=force_rescan,
    )
    if as_draft:
        return result
    batch, file_payloads, response = result
    background_tasks.add_task(
        process_ocr_batch,
        batch.id,
        file_payloads,
        actor.user_id,
        auto_approve,
        force_rescan,
    )
    return response


@router.get("/batch/{batch_id}/status", response_model=OCRBatchStatusResponse)
async def get_batch_status(
    batch_id: int,
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    return OcrApiService(db).batch_status(_actor(scope), batch_id)


@router.get("/bills", response_model=List[OCRBillResponse])
async def get_ocr_bills(
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    return OcrApiService(db).list_bills(scope.user_id, company_id=scope.company_id)


@router.get("/bills/{bill_id}", response_model=OCRBillResponse)
async def get_ocr_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    return OcrApiService(db).get_bill(
        scope.user_id, bill_id, company_id=scope.company_id
    )


@router.get("/bills/{bill_id}/file")
async def preview_ocr_bill_file(
    bill_id: int,
    download: bool = Query(False),
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    body, mime, headers = OcrApiService(db).bill_file_stream(
        scope.user_id, bill_id, download=download, company_id=scope.company_id
    )
    return StreamingResponse(body, media_type=mime, headers=headers)


@router.get("/bills/{bill_id}/preview")
async def preview_ocr_bill_alias(
    bill_id: int,
    db: Session = Depends(get_db),
    scope: ExpenseScope = Depends(get_expense_scope),
):
    body, mime, headers = OcrApiService(db).bill_file_stream(
        scope.user_id, bill_id, download=False, company_id=scope.company_id
    )
    return StreamingResponse(body, media_type=mime, headers=headers)
