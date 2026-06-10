"""Expense file attachments — upload, list, stream, delete."""
from __future__ import annotations

from io import BytesIO
from typing import List, Tuple

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseFile, ExpenseStatus
from app.services.expense_access_service import ExpenseAccessService
from app.utils.expense_helpers import expense_file_to_response
from app.utils.file_upload import process_multiple_files


class ExpenseFileService:
    def __init__(self, db: Session):
        self.db = db
        self.access = ExpenseAccessService(db)

    def _get_owned_file(
        self, expense_id: int, file_id: int, user_id: int
    ) -> ExpenseFile:
        expense_file = (
            self.db.query(ExpenseFile)
            .join(Expense)
            .filter(
                ExpenseFile.id == file_id,
                ExpenseFile.expense_id == expense_id,
                Expense.user_id == user_id,
            )
            .first()
        )
        if not expense_file:
            raise HTTPException(status_code=404, detail="File not found")
        return expense_file

    async def add_files(
        self, expense_id: int, user_id: int, files: List[UploadFile]
    ) -> List:
        expense = self.access.get_for_viewer(expense_id, user_id)
        if expense.status in (
            ExpenseStatus.APPROVED,
            ExpenseStatus.SUBMITTED,
            ExpenseStatus.PENDING,
        ):
            raise HTTPException(
                status_code=400,
                detail="Cannot add files to submitted or approved expense",
            )

        processed_files = await process_multiple_files(files)
        for file_data in processed_files:
            file_data["is_primary"] = False
            self.db.add(
                ExpenseFile(
                    expense_id=expense.id,
                    file_data=file_data["file_data"],
                    file_name=file_data["file_name"],
                    file_size=file_data["file_size"],
                    mime_type=file_data["mime_type"],
                    file_hash=file_data.get("file_hash"),
                    thumbnail_data=file_data.get("thumbnail_data"),
                    is_primary=False,
                )
            )
        self.db.commit()
        expense = self.access.get_for_viewer(expense_id, user_id)
        return [expense_file_to_response(expense_id, f) for f in expense.files]

    def list_files(self, expense_id: int, user_id: int) -> List:
        expense = self.access.get_for_viewer(expense_id, user_id)
        return [expense_file_to_response(expense_id, f) for f in expense.files]

    def file_stream(
        self, expense_id: int, file_id: int, user_id: int, *, download: bool
    ) -> Tuple[BytesIO, str, dict]:
        expense_file = self._get_owned_file(expense_id, file_id, user_id)
        disposition = "attachment" if download else "inline"
        headers = {
            "Content-Disposition": f'{disposition}; filename="{expense_file.file_name}"'
        }
        return BytesIO(expense_file.file_data), expense_file.mime_type, headers

    def thumbnail_stream(
        self, expense_id: int, file_id: int, user_id: int
    ) -> Tuple[BytesIO, str, dict]:
        expense_file = self._get_owned_file(expense_id, file_id, user_id)
        if not expense_file.thumbnail_data:
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        return (
            BytesIO(expense_file.thumbnail_data),
            "image/jpeg",
            {"Content-Disposition": "inline"},
        )

    def delete_file(self, expense_id: int, file_id: int, user_id: int) -> None:
        expense_file = self._get_owned_file(expense_id, file_id, user_id)
        if expense_file.expense.status == ExpenseStatus.APPROVED:
            raise HTTPException(
                status_code=400, detail="Cannot delete files from approved expense"
            )
        self.db.delete(expense_file)
        self.db.commit()

    def legacy_file_stream(
        self, expense_id: int, user_id: int, *, download: bool
    ) -> Tuple[BytesIO, str, str, dict]:
        expense = self.access.get_for_viewer(expense_id, user_id)
        if expense.files:
            primary = next((f for f in expense.files if f.is_primary), expense.files[0])
            data, name, mime = primary.file_data, primary.file_name, primary.mime_type
        elif expense.file_data:
            data, name, mime = expense.file_data, expense.file_name, expense.mime_type
        else:
            raise HTTPException(status_code=404, detail="File not found")
        disposition = "attachment" if download else "inline"
        headers = {"Content-Disposition": f'{disposition}; filename="{name}"'}
        return BytesIO(data), name, mime or "application/octet-stream", headers

    def legacy_thumbnail_stream(
        self, expense_id: int, user_id: int
    ) -> Tuple[BytesIO, str, dict]:
        expense = self.access.get_for_viewer(expense_id, user_id)
        thumb = None
        if expense.files:
            primary = next((f for f in expense.files if f.is_primary), expense.files[0])
            thumb = primary.thumbnail_data
        elif expense.thumbnail_data:
            thumb = expense.thumbnail_data
        if not thumb:
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        return BytesIO(thumb), "image/jpeg", {"Content-Disposition": "inline"}
