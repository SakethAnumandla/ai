"""Load expenses with viewer/submitter/approver access rules."""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Expense, OCRBill, User
from app.services.expense_approval_service import get_expense_for_viewer


class ExpenseAccessService:
    def __init__(self, db: Session):
        self.db = db

    def get_user(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_for_viewer(self, expense_id: int, user_id: int) -> Expense:
        user = self.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Expense not found")
        expense = get_expense_for_viewer(self.db, expense_id, user)
        if not expense:
            raise HTTPException(status_code=404, detail="Expense not found")
        return expense

    def get_ocr_bill(self, expense_id: int, user_id: int) -> Optional[OCRBill]:
        return (
            self.db.query(OCRBill)
            .filter(OCRBill.expense_id == expense_id, OCRBill.user_id == user_id)
            .first()
        )
