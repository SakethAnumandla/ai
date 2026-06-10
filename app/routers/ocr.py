# OCR HTTP routes — thin layer; logic in OcrApiService / ocr_draft_service.

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
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


@router.post("/scan-drafts", response_model=MultiBillDraftResponse)
async def scan_multiple_as_drafts(
    files: List[UploadFile] = File(...),
    force_rescan: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OcrApiService(db).scan_drafts(
        current_user, files, force_rescan=force_rescan
    )


@router.get("/batch/{batch_id}/drafts", response_model=MultiBillDraftResponse)
async def get_batch_drafts(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return OcrApiService(db).reload_batch_drafts(current_user, batch_id)


@router.post("/scan", response_model=ExpenseResponse)
async def scan_single_bill(
    file: UploadFile = File(...),
    as_draft: bool = Query(True),
    auto_approve: bool = False,
    force_rescan: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OcrApiService(db).scan_single(
        current_user,
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
    current_user: User = Depends(get_current_user),
):
    result = await OcrApiService(db).scan_batch(
        current_user,
        files,
        as_draft=as_draft,
        auto_approve=auto_approve,
        force_rescan=force_rescan,
    )
    if as_draft:
        return result
    batch, file_payloads, response = result
    import os

    if os.getenv("TESTING"):
        process_ocr_batch(
            batch.id,
            file_payloads,
            current_user.id,
            auto_approve,
            force_rescan,
        )
        return response
    background_tasks.add_task(
        process_ocr_batch,
        batch.id,
        file_payloads,
        current_user.id,
        auto_approve,
        force_rescan,
    )
    return response


@router.get("/batch/{batch_id}/status", response_model=OCRBatchStatusResponse)
async def get_batch_status(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return OcrApiService(db).batch_status(current_user, batch_id)


@router.get("/bills", response_model=List[OCRBillResponse])
async def get_ocr_bills(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return OcrApiService(db).list_bills(current_user.id)


@router.get("/bills/{bill_id}", response_model=OCRBillResponse)
async def get_ocr_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return OcrApiService(db).get_bill(current_user.id, bill_id)


@router.get("/bills/{bill_id}/file")
async def preview_ocr_bill_file(
    bill_id: int,
    download: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body, mime, headers = OcrApiService(db).bill_file_stream(
        current_user.id, bill_id, download=download
    )
    return StreamingResponse(body, media_type=mime, headers=headers)


@router.get("/bills/{bill_id}/preview")
async def preview_ocr_bill_alias(
    bill_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body, mime, headers = OcrApiService(db).bill_file_stream(
        current_user.id, bill_id, download=False
    )
    return StreamingResponse(body, media_type=mime, headers=headers)
