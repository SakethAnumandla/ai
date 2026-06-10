"""Multi-step expense approval workflow."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.data.business_taxonomy import (
    APPROVER_DIRECTORY,
    CEO_ONLY_APPROVAL_THRESHOLD_EUR,
    resolve_approval_roles,
)
from app.dependencies import DEV_USER_USERNAME
from app.models import ApprovalStatus, Expense, ExpenseApproval, ExpenseStatus, User
from app.schemas import ExpenseApprovalRemark, ExpenseApprovalRemarksResponse


def _roles_for_expense(expense: Expense) -> List[str]:
    """
    Approval chain by amount and taxonomy:
    - Large expenses → CEO only (L3)
    - Taxonomy may specify Manager only (L1), Manager+HOD (L1+L2), etc.
    """
    amount = float(expense.bill_amount or 0)
    if amount >= CEO_ONLY_APPROVAL_THRESHOLD_EUR:
        return ["ceo"]
    return resolve_approval_roles(
        expense.main_category.value if expense.main_category else None,
        expense.sub_category,
        expense.line_item,
    )


def _approval_sequence(roles: List[str]) -> List[Tuple[int, str]]:
    """Map roles to L1/L2/L3 sequence numbers for UI and export."""
    if roles == ["ceo"]:
        return [(3, "ceo")]
    return [(idx, role) for idx, role in enumerate(roles, start=1)]


def approval_chain_for_expense(expense: Expense) -> List[Dict[str, Any]]:
    """Approval levels — live steps if submitted, else planned from taxonomy."""
    mapping_title = {
        "manager": "Manager",
        "hod": "Head of Department",
        "hr": "HR Manager",
        "director": "Director",
        "finance": "Finance Lead",
        "admin": "Admin",
        "it": "IT Lead",
        "ceo": "CEO",
    }
    steps = sorted(expense.approval_steps or [], key=lambda s: s.sequence_order)
    if steps:
        return [
            {
                "level": s.sequence_order,
                "role": s.approval_level,
                "label": s.approver_role_label
                or mapping_title.get(s.approval_level or "", (s.approval_level or "").title()),
                "approver": s.approver_name,
                "status": s.status.value if s.status else "pending",
                "comments": s.comments,
            }
            for s in steps
        ]
    planned = _roles_for_expense(expense)
    out: List[Dict[str, Any]] = []
    for seq, role in _approval_sequence(planned):
        person = _pick_approver(role)
        out.append(
            {
                "level": seq,
                "role": role,
                "label": person.get("title") or mapping_title.get(role, role.title()),
                "approver": person.get("name"),
                "status": "planned",
                "comments": None,
            }
        )
    return out


def approval_remarks_for_expense(expense: Expense) -> List[ExpenseApprovalRemark]:
    """Approver remarks visible in bill details after approve/reject decisions."""
    steps = sorted(expense.approval_steps or [], key=lambda s: s.sequence_order)
    remarks: List[ExpenseApprovalRemark] = []
    for s in steps:
        if s.status not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            continue
        if not (s.comments and str(s.comments).strip()):
            continue
        text = s.comments.strip()
        remarks.append(
            ExpenseApprovalRemark(
                approval_id=s.id,
                level=s.sequence_order,
                role=s.approval_level,
                role_label=s.approver_role_label or s.approval_level,
                approver=s.approver_name,
                action=s.status.value if s.status else "pending",
                remarks=text,
                comments=text,
                acted_at=s.acted_at,
            )
        )
    return remarks


def build_expense_approval_remarks_payload(expense: Expense) -> ExpenseApprovalRemarksResponse:
    """Payload for GET /expenses/{id}/approval-remarks."""
    table = approval_remarks_for_expense(expense)
    return ExpenseApprovalRemarksResponse(
        expense_id=expense.id,
        expense_id_label=f"EXP-{expense.id:04d}",
        status=expense.status.value if expense.status else "draft",
        count=len(table),
        remarks_table=table,
    )


def _pick_approver(role: str) -> Dict[str, Any]:
    for row in APPROVER_DIRECTORY:
        if row["role"] == role:
            return row
    return {"id": None, "role": role, "name": role.title(), "title": role.title()}


def _resolve_approver_user_id(db: Session, person: Dict[str, Any]) -> Optional[int]:
    raw_id = person.get("id")
    if raw_id is not None:
        if db.query(User).filter(User.id == int(raw_id)).first():
            return int(raw_id)
    name = (person.get("name") or "").strip()
    if name:
        match = (
            db.query(User)
            .filter(func.lower(User.full_name) == name.lower())
            .first()
        )
        if match:
            return match.id
    # Local dev: directory IDs (101, 201, …) are not real users — bind to dev user.
    dev = db.query(User).filter(User.username == DEV_USER_USERNAME).first()
    return dev.id if dev else None


def first_pending_approval_step(expense: Expense) -> Optional[ExpenseApproval]:
    steps = sorted(expense.approval_steps or [], key=lambda s: s.sequence_order)
    return next((s for s in steps if s.status == ApprovalStatus.PENDING), None)


def user_can_act_on_step(db: Session, user: User, step: ExpenseApproval) -> bool:
    """Whether [user] may approve/reject this workflow step now."""
    if step.status != ApprovalStatus.PENDING:
        return False
    # Local dev: default user acts as stand-in for directory approvers (IDs 101, 201, …).
    if user.username == DEV_USER_USERNAME:
        return True
    if step.approver_id is not None and step.approver_id == user.id:
        return True
    if step.approver_id is None:
        return True
    approver_name = (step.approver_name or "").strip().lower()
    user_name = (user.full_name or user.username or "").strip().lower()
    if approver_name and user_name and (
        approver_name in user_name or user_name in approver_name
    ):
        return True
    return False


def user_can_view_expense(db: Session, expense_id: int, user: User) -> bool:
    expense = (
        db.query(Expense)
        .options(joinedload(Expense.approval_steps))
        .filter(Expense.id == expense_id)
        .first()
    )
    if not expense:
        return False
    if expense.user_id == user.id:
        return True
    steps = expense.approval_steps or []
    if not steps:
        return False
    pending = first_pending_approval_step(expense)
    if pending and user_can_act_on_step(db, user, pending):
        return True
    return any(
        s.approver_id == user.id
        and s.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)
        for s in steps
    )


def get_expense_for_viewer(db: Session, expense_id: int, user: User) -> Optional[Expense]:
    expense = (
        db.query(Expense)
        .options(
            joinedload(Expense.files),
            joinedload(Expense.tax_lines),
            joinedload(Expense.approval_steps),
        )
        .filter(Expense.id == expense_id)
        .first()
    )
    if not expense:
        return None
    if user_can_view_expense(db, expense_id, user):
        return expense
    return None


def create_expense_approval_workflow(db: Session, expense: Expense) -> List[ExpenseApproval]:
    """Create L1 / L2 / L3 steps when expense is submitted."""
    db.query(ExpenseApproval).filter(ExpenseApproval.expense_id == expense.id).delete()
    roles = _roles_for_expense(expense)
    steps: List[ExpenseApproval] = []
    for seq, role in _approval_sequence(roles):
        person = _pick_approver(role)
        step = ExpenseApproval(
            expense_id=expense.id,
            approval_level=role,
            sequence_order=seq,
            approver_id=_resolve_approver_user_id(db, person),
            approver_name=person.get("name"),
            approver_role_label=person.get("title"),
            status=ApprovalStatus.PENDING,
        )
        db.add(step)
        steps.append(step)
    db.flush()
    return steps


def get_workflow_progress(expense: Expense) -> List[Dict[str, Any]]:
    """Progress bar: draft → submitted → L1 → L2 → L3 → approved/rejected."""
    status = expense.status.value if expense.status else "draft"
    steps = sorted(expense.approval_steps or [], key=lambda s: s.sequence_order)
    submitted_label = (
        "Pending approval"
        if status in ("submitted", "pending")
        else "Submitted"
    )
    progress = [
        {"key": "draft", "label": "Draft", "state": "done" if status != "draft" else "current"},
        {
            "key": "submitted",
            "label": submitted_label,
            "state": "done"
            if status in ("submitted", "approved", "rejected", "pending")
            else ("current" if status == "draft" else "pending"),
        },
    ]
    for step in steps:
        st = step.status.value if step.status else "pending"
        if st == "approved":
            state = "done"
        elif st == "rejected":
            state = "rejected"
        elif status == "submitted" and step.sequence_order == _first_pending_seq(steps):
            state = "current"
        else:
            state = "pending"
        level_label = step.approver_role_label or step.approval_level or ""
        if step.sequence_order == 3 and (step.approval_level or "") == "ceo":
            level_label = level_label or "CEO"
        progress.append(
            {
                "key": f"L{step.sequence_order}",
                "label": level_label,
                "approver": step.approver_name,
                "state": state,
                "comments": step.comments,
                "acted_at": step.acted_at.isoformat() if step.acted_at else None,
            }
        )
    if status == "approved":
        final_state = "done"
        final_label = "Approved"
    elif status == "rejected":
        final_state = "rejected"
        final_label = "Rejected"
    else:
        final_state = "pending"
        final_label = "Approved"
    progress.append(
        {
            "key": "final",
            "label": final_label,
            "state": final_state,
        }
    )
    return progress


def _first_pending_seq(steps: List[ExpenseApproval]) -> int:
    for s in steps:
        if s.status == ApprovalStatus.PENDING:
            return s.sequence_order
    return 999


def approval_stage_label(expense: Expense) -> Optional[str]:
    status = expense.status
    if status == ExpenseStatus.DRAFT:
        return None
    if status == ExpenseStatus.APPROVED:
        return "Approved"
    if status == ExpenseStatus.REJECTED:
        return "Rejected"

    steps = sorted(expense.approval_steps or [], key=lambda s: s.sequence_order)
    if not steps:
        if status in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
            return "Pending approval"
        return None

    approved_steps = [s for s in steps if s.status == ApprovalStatus.APPROVED]
    pending_steps = [s for s in steps if s.status == ApprovalStatus.PENDING]
    rejected = next((s for s in steps if s.status == ApprovalStatus.REJECTED), None)
    if rejected:
        role = rejected.approver_role_label or f"L{rejected.sequence_order}"
        return f"Rejected at {role}"

    if approved_steps and pending_steps:
        last_done = approved_steps[-1]
        next_wait = pending_steps[0]
        done_n = last_done.sequence_order
        wait_n = next_wait.sequence_order
        wait_role = next_wait.approver_role_label or next_wait.approval_level
        if len(steps) == 1 and (next_wait.approval_level or "") == "ceo":
            return "Pending CEO (L3) approval"
        return f"L{done_n} approved — waiting for L{wait_n} ({wait_role}) approval"

    if pending_steps:
        first = pending_steps[0]
        role = first.approver_role_label or first.approval_level
        if len(steps) == 1 and (first.approval_level or "") == "ceo":
            return "Pending CEO (L3) approval"
        return f"Pending L{first.sequence_order} ({role}) approval"

    return "Pending approval"


def process_expense_approval(
    db: Session,
    *,
    approval_id: int,
    user: User,
    action: str,
    comments: Optional[str] = None,
) -> Expense:
    step = db.query(ExpenseApproval).filter(ExpenseApproval.id == approval_id).first()
    if not step:
        raise ValueError("Approval step not found")
    expense = db.query(Expense).filter(Expense.id == step.expense_id).first()
    if not expense:
        raise ValueError("Expense not found")
    if expense.status not in (ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING):
        raise ValueError("Expense is not awaiting approval")

    prior = (
        db.query(ExpenseApproval)
        .filter(
            ExpenseApproval.expense_id == expense.id,
            ExpenseApproval.sequence_order < step.sequence_order,
        )
        .all()
    )
    if any(p.status != ApprovalStatus.APPROVED for p in prior):
        raise ValueError("Earlier approval steps must be completed first")

    now = datetime.now(timezone.utc)
    actor = user or (db.query(User).filter(User.id == expense.user_id).first())
    if actor and not user_can_act_on_step(db, actor, step):
        raise ValueError("You are not authorized to act on this approval step")

    if action == "approve":
        if not comments or not str(comments).strip():
            raise ValueError("Approval remarks are required")
        step.status = ApprovalStatus.APPROVED
        if actor and step.approver_id is None:
            step.approver_id = actor.id
            if not step.approver_name:
                step.approver_name = actor.full_name or actor.username
        step.comments = comments.strip()
        step.acted_at = now
        next_pending = (
            db.query(ExpenseApproval)
            .filter(
                ExpenseApproval.expense_id == expense.id,
                ExpenseApproval.sequence_order > step.sequence_order,
                ExpenseApproval.status == ApprovalStatus.PENDING,
            )
            .order_by(ExpenseApproval.sequence_order)
            .first()
        )
        if not next_pending:
            expense.status = ExpenseStatus.APPROVED
            expense.approved_at = now
            from app.services.wallet_service import WalletService

            WalletService(db).update_wallet_balance(expense.user_id, expense)
        db.flush()
    elif action == "reject":
        if not comments or not str(comments).strip():
            raise ValueError("Rejection remarks are required")
        remark_text = str(comments).strip()
        step.status = ApprovalStatus.REJECTED
        step.comments = remark_text
        step.acted_at = now
        if actor and step.approver_id is None:
            step.approver_id = actor.id
            if not step.approver_name:
                step.approver_name = actor.full_name or actor.username
        expense.status = ExpenseStatus.REJECTED
        expense.rejection_reason = remark_text
        db.flush()
    else:
        raise ValueError("action must be approve or reject")
    return expense


def approve_expense_current_step(
    db: Session,
    expense: Expense,
    *,
    action: str,
    comments: Optional[str] = None,
    user: Optional[User] = None,
) -> Expense:
    """Approve/reject the next pending workflow step for an expense."""
    steps = sorted(expense.approval_steps or [], key=lambda s: s.sequence_order)
    pending = next((s for s in steps if s.status == ApprovalStatus.PENDING), None)
    if not pending:
        raise ValueError("No pending approval step for this expense")
    if user is None:
        user = db.query(User).filter(User.id == expense.user_id).first()
    if not user:
        raise ValueError("User not found")
    return process_expense_approval(
        db,
        approval_id=pending.id,
        user=user,
        action=action,
        comments=comments,
    )


def list_pending_for_user(db: Session, user_id: int) -> List[ExpenseApproval]:
    """One actionable pending step per expense (L1 before L2)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return []

    expenses = (
        db.query(Expense)
        .options(joinedload(Expense.approval_steps))
        .filter(Expense.status.in_((ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING)))
        .order_by(Expense.updated_at.desc())
        .all()
    )
    out: List[ExpenseApproval] = []
    for expense in expenses:
        pending = first_pending_approval_step(expense)
        if pending and user_can_act_on_step(db, user, pending):
            out.append(pending)
    return out


def pending_approval_groups_for_user(db: Session, user_id: int) -> List[Dict[str, Any]]:
    """Grouped pending queue with full chain + progress for the approval screen."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return []

    from app.utils.expense_helpers import submitted_by_display

    groups: List[Dict[str, Any]] = []
    for step in list_pending_for_user(db, user_id):
        expense = (
            db.query(Expense)
            .options(joinedload(Expense.approval_steps))
            .filter(Expense.id == step.expense_id)
            .first()
        )
        if not expense:
            continue
        all_steps = sorted(expense.approval_steps or [], key=lambda s: s.sequence_order)
        groups.append(
            {
                "expense_id": expense.id,
                "expense_id_label": f"EXP-{expense.id:04d}",
                "description": expense.bill_name,
                "main_category": expense.main_category.value if expense.main_category else None,
                "sub_category": expense.sub_category,
                "line_item": expense.line_item,
                "amount": expense.bill_amount,
                "currency_code": expense.currency_code or "EUR",
                "bill_date": expense.bill_date.isoformat() if expense.bill_date else None,
                "submitted_by": submitted_by_display(expense) or "—",
                "submitted_by_name": expense.submitted_by_name,
                "submitted_by_role": expense.submitted_by_role,
                "stage_label": approval_stage_label(expense),
                "progress": get_workflow_progress(expense),
                "actionable_approval_id": step.id,
                "steps": [
                    {
                        "approval_id": s.id,
                        "expense_id": expense.id,
                        "expense_id_label": f"EXP-{expense.id:04d}",
                        "description": expense.bill_name,
                        "amount": expense.bill_amount,
                        "currency_code": expense.currency_code or "EUR",
                        "bill_date": expense.bill_date.isoformat() if expense.bill_date else None,
                        "status": s.status.value if s.status else "pending",
                        "approval_level": s.approval_level,
                        "sequence_order": s.sequence_order,
                        "approver_name": s.approver_name,
                        "approver_role_label": s.approver_role_label,
                        "comments": s.comments,
                        "acted_at": s.acted_at.isoformat() if s.acted_at else None,
                        "is_actionable": s.id == step.id,
                        "submitted_by": submitted_by_display(expense) or "—",
                    }
                    for s in all_steps
                ],
            }
        )
    return groups


def build_pending_expense_approval_queue(db: Session, user_id: int) -> Dict[str, Any]:
    """Flat + grouped pending queue payload for GET /expenses/approvals/pending."""
    from app.data.business_taxonomy import APPROVER_DIRECTORY

    groups = pending_approval_groups_for_user(db, user_id)
    flat: List[Dict[str, Any]] = []
    for group in groups:
        for step in group.get("steps") or []:
            if step.get("is_actionable"):
                flat.append(
                    {
                        "approval_id": step["approval_id"],
                        "expense_id": group["expense_id"],
                        "expense_id_label": group["expense_id_label"],
                        "description": group["description"],
                        "main_category": group.get("main_category"),
                        "sub_category": group.get("sub_category"),
                        "line_item": group.get("line_item"),
                        "amount": group["amount"],
                        "currency_code": group.get("currency_code", "EUR"),
                        "bill_date": group.get("bill_date"),
                        "status": step.get("status", "pending"),
                        "approval_level": step.get("approval_level"),
                        "sequence_order": step.get("sequence_order"),
                        "approver_name": step.get("approver_name"),
                        "approver_role_label": step.get("approver_role_label"),
                        "submitted_by": group.get("submitted_by"),
                        "submitted_by_name": group.get("submitted_by_name"),
                        "submitted_by_role": group.get("submitted_by_role"),
                        "stage_label": group.get("stage_label"),
                    }
                )
    return {
        "pending": flat,
        "count": len(flat),
        "groups": groups,
        "approvers": APPROVER_DIRECTORY,
    }


def build_expense_approval_workflow_payload(
    expense: Expense,
) -> Dict[str, Any]:
    """Workflow detail payload for GET /expenses/{id}/approval-workflow."""
    remarks = approval_remarks_for_expense(expense)
    return {
        "expense_id": expense.id,
        "status": expense.status.value,
        "stage_label": approval_stage_label(expense),
        "progress": get_workflow_progress(expense),
        "remarks_table": [row.model_dump(mode="json") for row in remarks],
        "approval_remarks": [row.model_dump(mode="json") for row in remarks],
        "steps": [
            {
                "id": step.id,
                "level": step.approval_level,
                "sequence": step.sequence_order,
                "approver_name": step.approver_name,
                "approver_role": step.approver_role_label,
                "status": step.status.value if step.status else "pending",
                "comments": step.comments,
                "acted_at": step.acted_at.isoformat() if step.acted_at else None,
            }
            for step in sorted(expense.approval_steps or [], key=lambda s: s.sequence_order)
        ],
    }
