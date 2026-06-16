"""Expense tool handlers — delegate to ExpenseService only."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload

from app.ai.schemas.common import SessionContext
from app.ai.workflow.slot_parser import (
    food_sub_category_prompt,
    is_payment_method_text,
    sanitize_sub_category,
)
from app.ai.schemas.tool_result import ToolResult
from app.ai.vendor_guard import looks_like_chat_command, sanitize_vendor_name
from app.intelligence.receipt.human_review import HumanReviewService
from app.models import (
    ApprovalStatus,
    Expense,
    ExpenseApproval,
    ExpenseStatus,
    MainCategory,
    OCRBill,
    TransactionType,
    UploadMethod,
    User,
)
from app.services.expense_approval_service import (
    get_workflow_progress,
    list_pending_for_user,
    process_expense_approval,
)
from app.utils.dashboard_queries import expense_status_display
from app.schemas import ExpenseCreate, ExpenseUpdate
from app.services.expense_service import ExpenseService
def _money_label(amount: float, currency: Optional[str] = None) -> str:
    if amount == int(amount):
        return f"{int(amount):,}"
    return f"{amount:,.2f}"


def _parse_category(value: Optional[str]) -> MainCategory:
    if not value:
        return MainCategory.MISCELLANEOUS
    try:
        return MainCategory(value.lower().strip())
    except ValueError:
        return MainCategory.MISCELLANEOUS


def _corrections_from_kwargs(
    *,
    bill_name: Optional[str],
    bill_amount: Optional[float],
    vendor_name: Optional[str],
) -> Dict[str, Any]:
    corrections: Dict[str, Any] = {}
    if bill_amount is not None and float(bill_amount) > 0:
        corrections["bill_amount"] = float(bill_amount)
    clean_vendor = sanitize_vendor_name(vendor_name)
    if clean_vendor:
        corrections["vendor_name"] = clean_vendor
    if bill_name:
        corrections["bill_name"] = bill_name
    return corrections


async def handle_expense_create_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    bill_name: str,
    bill_amount: Optional[float] = None,
    main_category: Optional[str] = None,
    sub_category: Optional[str] = None,
    vendor_name: Optional[str] = None,
    payment_method: Optional[str] = None,
    description: Optional[str] = None,
    hashtags: Optional[list] = None,
    bill_date: Optional[str] = None,
    expense_id: Optional[int] = None,
    review_token: Optional[str] = None,
    save_as_draft: bool = False,
    **_,
) -> ToolResult:
    logger.info(
        "expense.create.v1 handler args bill_name=%s amount=%s vendor=%s category=%s sub=%s payment=%s tags=%s",
        bill_name,
        bill_amount,
        vendor_name,
        main_category,
        sub_category,
        payment_method,
        hashtags,
    )
    if expense_id is not None:
        return await _confirm_existing_draft(
            db=db,
            user=user,
            expense_id=int(expense_id),
            bill_name=bill_name,
            bill_amount=bill_amount,
            main_category=main_category,
            sub_category=sub_category,
            vendor_name=vendor_name,
            bill_date=bill_date,
            review_token=review_token,
            save_as_draft=save_as_draft,
        )

    if bill_amount is None or float(bill_amount) <= 0:
        return ToolResult.fail(
            "What was the amount for this expense?",
            error="missing_amount",
            data={"bill_name": bill_name, "needs_clarification": True},
        )

    parsed_date = datetime.utcnow()
    if bill_date:
        from app.utils.date_parser import parse_bill_date
        try:
            parsed_date = parse_bill_date(bill_date)
        except Exception:
            pass

    parsed_main = _parse_category(main_category)
    if sub_category and is_payment_method_text(sub_category):
        sub_category = None
    clean_sub = sanitize_sub_category(
        parsed_main.value,
        sub_category,
        vendor_name=vendor_name,
        bill_name=bill_name,
    )
    try:
        expense_payload = {
            "bill_name": bill_name,
            "bill_amount": float(bill_amount),
            "bill_date": parsed_date,
            "transaction_type": TransactionType.EXPENSE,
            "main_category": parsed_main,
            "sub_category": clean_sub,
            "vendor_name": sanitize_vendor_name(vendor_name),
            "payment_method": payment_method,
            "description": (description or "").strip() or None,
            "hashtags": hashtags or None,
        }
        logger.info("FINAL EXPENSE PAYLOAD => %s", expense_payload)
        expense_data = ExpenseCreate(**expense_payload)
    except ValidationError:
        if parsed_main.value == "food":
            return ToolResult.fail(
                food_sub_category_prompt(),
                error="invalid_sub_category",
                data={"needs_clarification": True, "field": "sub_category"},
            )
        return ToolResult.fail(
            "I couldn't save that category. Could you pick a valid category?",
            error="invalid_sub_category",
            data={"needs_clarification": True},
        )

    status = ExpenseStatus.DRAFT if save_as_draft else ExpenseStatus.SUBMITTED
    try:
        expense = ExpenseService.create_expense(
            db, expense_data, user.id, UploadMethod.MANUAL, status=status
        )
    except ValidationError:
        if parsed_main.value == "food":
            return ToolResult.fail(
                food_sub_category_prompt(),
                error="invalid_sub_category",
                data={"needs_clarification": True, "field": "sub_category"},
            )
        raise
    if save_as_draft:
        message = (
            f"Saved draft expense '{expense.bill_name}' for ₹{expense.bill_amount:,.2f}. "
            "Say when you want to submit it for approval."
        )
    else:
        message = (
            f"Done 👍 Submitted '{expense.bill_name}' (₹{expense.bill_amount:,.2f}) for approval."
        )
    return ToolResult.ok(
        message=message,
        data={"expense_id": expense.id, "status": expense.status.value},
    )


async def _confirm_existing_draft(
    *,
    db: Session,
    user: User,
    expense_id: int,
    bill_name: str,
    bill_amount: Optional[float],
    main_category: Optional[str],
    sub_category: Optional[str],
    vendor_name: Optional[str],
    payment_method: Optional[str] = None,
    description: Optional[str] = None,
    hashtags: Optional[list] = None,
    bill_date: Optional[str],
    review_token: Optional[str],
    save_as_draft: bool,
) -> ToolResult:
    svc = ExpenseService(db)
    expense = svc.get_expense(expense_id, user.id)
    if not expense:
        return ToolResult.fail("Expense not found", error="not_found")
    if expense.status not in (
        ExpenseStatus.DRAFT,
        ExpenseStatus.PENDING,
        ExpenseStatus.REJECTED,
    ):
        return ToolResult.fail(
            f"Cannot update expense in status {expense.status.value}",
            error="invalid_status",
        )

    corrections = _corrections_from_kwargs(
        bill_name=bill_name,
        bill_amount=bill_amount,
        vendor_name=vendor_name,
    )

    if review_token:
        try:
            expense = HumanReviewService(db).confirm_review(
                user_id=user.id,
                expense_id=expense_id,
                review_token=review_token,
                corrections=corrections or None,
            )
        except ValueError as exc:
            return ToolResult.fail(str(exc), error="review_confirm_failed")

    update_fields: Dict[str, Any] = {}
    if bill_name:
        update_fields["bill_name"] = bill_name
    if bill_amount is not None and float(bill_amount) > 0:
        update_fields["bill_amount"] = float(bill_amount)
    clean_vendor = sanitize_vendor_name(vendor_name)
    if not clean_vendor and (
        not expense.vendor_name or looks_like_chat_command(expense.vendor_name)
    ):
        bill = (
            db.query(OCRBill)
            .filter(OCRBill.expense_id == expense_id, OCRBill.user_id == user.id)
            .first()
        )
        if bill:
            clean_vendor = sanitize_vendor_name(
                bill.vendor_name or bill.restaurant_name
            )
    if clean_vendor:
        update_fields["vendor_name"] = clean_vendor
    if main_category:
        update_fields["main_category"] = _parse_category(main_category)
    if sub_category:
        clean_sub = sanitize_sub_category(
            (main_category or expense.main_category.value if expense.main_category else None),
            sub_category,
            vendor_name=vendor_name or expense.vendor_name,
            bill_name=bill_name or expense.bill_name,
        )
        if clean_sub:
            update_fields["sub_category"] = clean_sub
    if payment_method:
        update_fields["payment_method"] = payment_method
    if description is not None:
        update_fields["description"] = description
    if hashtags:
        update_fields["hashtags"] = hashtags
    if bill_date:
        from app.utils.date_parser import parse_bill_date
        try:
            update_fields["bill_date"] = parse_bill_date(bill_date)
        except Exception:
            pass

    if update_fields:
        try:
            expense = svc.update_expense(
                expense_id, user.id, ExpenseUpdate(**update_fields)
            )
        except ValidationError:
            return ToolResult.fail(
                food_sub_category_prompt(),
                error="invalid_sub_category",
                data={"needs_clarification": True, "field": "sub_category"},
            )

    if not save_as_draft and expense.status in (
        ExpenseStatus.DRAFT,
        ExpenseStatus.PENDING,
        ExpenseStatus.REJECTED,
    ):
        expense = svc.submit_for_approval(expense_id, user.id)

    status_note = (
        " and submitted for approval"
        if expense.status == ExpenseStatus.SUBMITTED
        else ""
    )
    return ToolResult.ok(
        message=(
            f"Confirmed expense #{expense.id} "
            f"({expense.bill_name}, ₹{expense.bill_amount:,.2f}){status_note}."
        ),
        data={
            "expense_id": expense.id,
            "status": expense.status.value,
            "confirmed": True,
        },
    )


async def handle_expense_submit_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    expense_id: int,
    idempotency_key: str,
    **_,
) -> ToolResult:
    svc = ExpenseService(db)
    expense = svc.get_expense(expense_id, user.id)
    if not expense:
        return ToolResult.fail("Expense not found", error="not_found")
    if expense.status not in (
        ExpenseStatus.DRAFT,
        ExpenseStatus.PENDING,
        ExpenseStatus.SUBMITTED,
        ExpenseStatus.REJECTED,
    ):
        return ToolResult.fail(
            f"Cannot submit expense in status {expense.status.value}",
            error="invalid_status",
        )
    if expense.status == ExpenseStatus.SUBMITTED:
        return ToolResult.ok(
            message=(
                f"Expense #{expense.id} ({expense.bill_name}, "
                f"₹{expense.bill_amount:,.2f}) is already submitted for approval."
            ),
            data={"expense_id": expense.id, "status": expense.status.value},
        )
    updated = svc.submit_for_approval(expense_id, user.id)
    return ToolResult.ok(
        message=f"Expense #{updated.id} ({updated.bill_name}, ₹{updated.bill_amount:,.2f}) submitted for approval.",
        data={"expense_id": updated.id, "status": updated.status.value},
    )


async def handle_expense_search_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    search_term: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 10,
    **_,
) -> ToolResult:
    from app.ai.utils.expense_search import (
        format_expense_search_message,
        resolve_expense_search_statuses,
    )

    svc = ExpenseService(db)
    exp_status, exp_statuses, pending_view = resolve_expense_search_statuses(status)
    effective_limit = min(limit if limit > 0 else 10, 50)
    if pending_view and effective_limit < 50:
        effective_limit = 50
    parsed_start = parsed_end = None
    if start_date or end_date:
        from app.ai.utils.date_range_parser import parse_date_range

        if start_date and end_date:
            parsed = parse_date_range(f"{start_date} to {end_date}")
        else:
            parsed = parse_date_range(start_date or end_date or "")
        if parsed:
            parsed_start, parsed_end = parsed
    expenses, total = svc.get_user_expenses(
        user.id,
        status=exp_status,
        statuses=exp_statuses,
        search_term=search_term,
        start_date=parsed_start,
        end_date=parsed_end,
        limit=effective_limit,
    )
    items = [
        {
            "expense_id": e.id,
            "bill_name": e.bill_name,
            "bill_amount": e.bill_amount,
            "vendor_name": e.vendor_name,
            "status": expense_status_display(e.status),
            "bill_date": e.bill_date.isoformat() if e.bill_date else None,
        }
        for e in expenses
    ]
    message = format_expense_search_message(items, total, pending_view=pending_view)
    return ToolResult.ok(
        message=message,
        data={"expenses": items, "total": total, "pending_view": pending_view},
    )


async def handle_expense_update_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    expense_id: int,
    bill_name: Optional[str] = None,
    bill_amount: Optional[float] = None,
    vendor_name: Optional[str] = None,
    main_category: Optional[str] = None,
    sub_category: Optional[str] = None,
    bill_date: Optional[str] = None,
    description: Optional[str] = None,
    **_,
) -> ToolResult:
    svc = ExpenseService(db)
    expense = svc.get_expense(expense_id, user.id)
    if not expense:
        return ToolResult.fail("Expense not found", error="not_found")

    update_fields: Dict[str, Any] = {}
    if bill_name:
        update_fields["bill_name"] = bill_name
    if bill_amount is not None:
        update_fields["bill_amount"] = float(bill_amount)
    clean_vendor = sanitize_vendor_name(vendor_name)
    if clean_vendor:
        update_fields["vendor_name"] = clean_vendor
    if main_category:
        update_fields["main_category"] = _parse_category(main_category)
    if sub_category:
        clean_sub = sanitize_sub_category(
            (main_category or expense.main_category.value if expense.main_category else None),
            sub_category,
            vendor_name=vendor_name or expense.vendor_name,
            bill_name=bill_name or expense.bill_name,
        )
        if clean_sub:
            update_fields["sub_category"] = clean_sub
    if description is not None:
        update_fields["description"] = description
    if bill_date:
        from app.utils.date_parser import parse_bill_date
        try:
            update_fields["bill_date"] = parse_bill_date(bill_date)
        except Exception:
            return ToolResult.fail("Invalid date format", error="invalid_date")

    if not update_fields:
        return ToolResult.fail(
            "No fields to update. Specify amount, vendor, category, or date.",
            error="no_fields",
        )

    try:
        updated = svc.update_expense(expense_id, user.id, ExpenseUpdate(**update_fields))
    except ValidationError:
        return ToolResult.fail(
            food_sub_category_prompt(),
            error="invalid_sub_category",
            data={"needs_clarification": True, "field": "sub_category"},
        )
    return ToolResult.ok(
        message=(
            f"Updated expense #{updated.id} "
            f"({updated.vendor_name or updated.bill_name}, ₹{updated.bill_amount:,.2f})."
        ),
        data={"expense_id": updated.id, "status": updated.status.value},
    )


async def handle_expense_delete_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    expense_id: int,
    **_,
) -> ToolResult:
    svc = ExpenseService(db)
    expense = svc.get_expense(expense_id, user.id)
    if not expense:
        return ToolResult.fail("Expense not found", error="not_found")
    if expense.status == ExpenseStatus.APPROVED:
        return ToolResult.fail(
            "Approved expenses cannot be deleted from chat. Contact finance if needed.",
            error="invalid_status",
        )
    label = expense.vendor_name or expense.bill_name
    svc.delete_expense(expense_id, user.id)
    return ToolResult.ok(
        message=f"Deleted expense #{expense_id} ({label}, {_money_label(expense.bill_amount)}).",
        data={"expense_id": expense_id},
    )


def _load_expense_for_user(db: Session, user: User, expense_id: int) -> Optional[Expense]:
    expense = (
        db.query(Expense)
        .options(joinedload(Expense.approval_steps))
        .filter(Expense.id == expense_id)
        .first()
    )
    if not expense:
        return None
    if expense.user_id == user.id:
        return expense
    approver_step = (
        db.query(ExpenseApproval)
        .filter(
            ExpenseApproval.expense_id == expense_id,
            ExpenseApproval.approver_id == user.id,
        )
        .first()
    )
    if approver_step:
        return expense
    return None


def _expense_status_payload(expense: Expense) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expense_id": expense.id,
        "expense_id_label": f"EXP-{expense.id:04d}",
        "bill_name": expense.bill_name,
        "bill_amount": expense.bill_amount,
        "vendor_name": expense.vendor_name,
        "status": expense_status_display(expense.status),
        "raw_status": expense.status.value if expense.status else None,
        "main_category": expense.main_category.value if expense.main_category else None,
        "sub_category": expense.sub_category,
        "line_item": expense.line_item,
        "bill_date": expense.bill_date.isoformat() if expense.bill_date else None,
        "progress": get_workflow_progress(expense),
    }
    if expense.currency_code:
        payload["currency_code"] = expense.currency_code
    return payload


async def handle_expense_get_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    expense_id: int,
    **_,
) -> ToolResult:
    expense = _load_expense_for_user(db, user, expense_id)
    if not expense:
        return ToolResult.fail("Expense not found", error="not_found")
    payload = _expense_status_payload(expense)
    label = payload["expense_id_label"]
    status = payload["status"]
    amount = _money_label(expense.bill_amount)
    return ToolResult.ok(
        message=f"{label} — {expense.bill_name} ({amount}): {status}.",
        data=payload,
    )


async def handle_expense_approval_pending_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    **_,
) -> ToolResult:
    steps = list_pending_for_user(db, user.id)
    if not steps:
        steps = (
            db.query(ExpenseApproval)
            .options(joinedload(ExpenseApproval.expense))
            .filter(ExpenseApproval.status == ApprovalStatus.PENDING)
            .order_by(ExpenseApproval.created_at.desc())
            .limit(50)
            .all()
        )
    pending = []
    for step in steps:
        exp = step.expense
        if not exp:
            continue
        pending.append(
            {
                "approval_id": step.id,
                "expense_id": exp.id,
                "expense_id_label": f"EXP-{exp.id:04d}",
                "description": exp.bill_name,
                "main_category": exp.main_category.value if exp.main_category else None,
                "sub_category": exp.sub_category,
                "line_item": exp.line_item,
                "amount": exp.bill_amount,
                "bill_date": exp.bill_date.isoformat() if exp.bill_date else None,
                "status": step.status.value if step.status else "pending",
                "approval_level": step.approval_level,
                "sequence_order": step.sequence_order,
                "approver_name": step.approver_name,
                "approver_role_label": step.approver_role_label,
            }
        )
    if not pending:
        return ToolResult.ok(
            message="No expense bills are waiting for your approval right now.",
            data={"pending": [], "count": 0},
        )
    lines = [
        f"• {p['expense_id_label']} — {p['description']} "
        f"({_money_label(p['amount'])})"
        for p in pending[:10]
    ]
    more = f" (+{len(pending) - 10} more)" if len(pending) > 10 else ""
    return ToolResult.ok(
        message=f"{len(pending)} bill(s) awaiting approval:\n" + "\n".join(lines) + more,
        data={"pending": pending, "count": len(pending)},
    )


async def handle_expense_approval_action_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    approval_id: int,
    action: str,
    idempotency_key: str,
    comments: Optional[str] = None,
    **_,
) -> ToolResult:
    act = (action or "").strip().lower()
    if act not in ("approve", "reject"):
        return ToolResult.fail(
            "action must be 'approve' or 'reject'",
            error="invalid_action",
        )
    try:
        expense = process_expense_approval(
            db,
            approval_id=approval_id,
            user=user,
            action=act,
            comments=comments,
        )
    except ValueError as exc:
        return ToolResult.fail(str(exc), error="approval_failed")
    payload = _expense_status_payload(expense)
    verb = "Approved" if act == "approve" else "Rejected"
    return ToolResult.ok(
        message=(
            f"{verb} {payload['expense_id_label']} — {expense.bill_name} "
            f"({_money_label(expense.bill_amount)}). "
            f"Status: {payload['status']}."
        ),
        data={
            **payload,
            "approval_id": approval_id,
            "action": act,
        },
    )
