# Expense workflow router — thin HTTP layer

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.data.business_taxonomy import APPROVER_DIRECTORY, get_taxonomy_hierarchy
from app.database import get_db
from app.dependencies import get_current_user
from app.domain.workflow_schemas import ExpenseApprovalAction
from app.models import User
from app.services.budget_service import monthly_budget_grid
from app.services.export_service import ExportService
from app.services.expense_approval_service import (
    build_expense_approval_workflow_payload,
    build_pending_expense_approval_queue,
    get_expense_for_viewer,
    process_expense_approval,
)
from app.utils.expense_helpers import build_expense_response

router = APIRouter(tags=["expense-workflow"])


@router.get("/categories/business/hierarchy")
async def business_category_hierarchy():
    return get_taxonomy_hierarchy()


@router.get("/expenses/approvers/directory")
async def approver_directory():
    return {"approvers": APPROVER_DIRECTORY}


@router.get("/expenses/approvals/pending")
async def pending_expense_approvals(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Expenses awaiting action by current user (sequential L1 → L2 → L3)."""
    return build_pending_expense_approval_queue(db, user.id)


@router.get("/expenses/{expense_id}/approval-workflow")
async def expense_approval_workflow(
    expense_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    expense = get_expense_for_viewer(db, expense_id, user)
    if not expense:
        raise HTTPException(404, "Expense not found")
    return build_expense_approval_workflow_payload(expense)


@router.post("/expenses/approvals/{approval_id}/action")
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


@router.get("/budgets/monthly")
async def monthly_budget_vs_actual(
    financial_year: str = Query("FY2025-26", description="e.g. FY2025-26"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Monthly budget grid (€1M target per month) vs approved spend."""
    try:
        return monthly_budget_grid(db, user.id, financial_year)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/dashboard/export-by-fy")
async def export_by_financial_year(
    financial_year: str = Query(..., description="FY2025-26 or FY2026-27"),
    group_by: str = Query("month", pattern="^(month|category)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export approved expenses grouped monthly or by category within a FY."""
    export_service = ExportService(db)
    try:
        return export_service.export_by_financial_year(
            user_id=user.id,
            financial_year=financial_year,
            group_by=group_by,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
