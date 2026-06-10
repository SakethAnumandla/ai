"""Policy claim submission, limit checks, approval workflow, expense linking."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.models import (
    ApprovalLevel,
    ApprovalStatus,
    Claim,
    ClaimApproval,
    ClaimStatus,
    Expense,
    ExpenseStatus,
    MainCategory,
    Policy,
    TransactionType,
    UploadMethod,
    User,
    UserRole,
)
from app.services.policy_service import PolicyService
from app.services.wallet_service import WalletService
from app.utils.expense_helpers import parse_payment_method
from app.utils.policy_tax import apply_policy_taxes_to_expense, merge_claim_tax_payload


class ClaimService:
    def __init__(self, db: Session):
        self.db = db
        self.policy_service = PolicyService(db)

    def validate_claim_against_policy(
        self, claim_amount: float, policy: Policy
    ) -> Dict[str, Any]:
        active = self.policy_service.validate_policy_active(policy)
        if not active["is_valid"]:
            return active

        if claim_amount < policy.minimum_amount:
            return {
                "is_valid": False,
                "reason": f"Amount {claim_amount} is below policy minimum {policy.minimum_amount}",
            }

        return {"is_valid": True, "reason": None}

    def exceeds_policy_limit(self, claim_amount: float, policy: Policy) -> bool:
        return claim_amount > policy.maximum_amount

    def calculate_approved_amount(self, claim_amount: float, policy: Policy) -> float:
        approved = claim_amount * (policy.coverage_percentage / 100.0)
        if approved > policy.maximum_amount:
            approved = policy.maximum_amount
        return round(approved, 2)

    def _generate_claim_number(self) -> str:
        return f"CLM-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    def _find_department_head(self, user: User) -> Optional[User]:
        if not user.department:
            return None
        return (
            self.db.query(User)
            .filter(
                User.department_head_for == user.department,
                User.role == UserRole.DEPARTMENT_HEAD,
                User.is_active.is_(True),
            )
            .first()
        )

    def _find_manager(self, user: User) -> Optional[User]:
        if user.manager_id:
            mgr = self.db.query(User).filter(User.id == user.manager_id).first()
            if mgr:
                return mgr
        if user.department:
            return (
                self.db.query(User)
                .filter(
                    User.department == user.department,
                    User.role == UserRole.MANAGER,
                    User.is_active.is_(True),
                )
                .first()
            )
        return self.db.query(User).filter(User.role == UserRole.MANAGER).first()

    def create_approval_workflow(self, claim: Claim, policy: Policy) -> List[ClaimApproval]:
        if not policy.requires_approval:
            return []

        user = self.db.query(User).filter(User.id == claim.user_id).first()
        approvals: List[ClaimApproval] = []
        seq = 1

        dept_head = self._find_department_head(user)
        if dept_head:
            approvals.append(
                ClaimApproval(
                    claim_id=claim.id,
                    approver_id=dept_head.id,
                    approval_level=ApprovalLevel.DEPARTMENT_HEAD,
                    sequence_order=seq,
                )
            )
            seq += 1

        manager = self._find_manager(user)
        if manager and (not dept_head or manager.id != dept_head.id):
            approvals.append(
                ClaimApproval(
                    claim_id=claim.id,
                    approver_id=manager.id,
                    approval_level=ApprovalLevel.MANAGER,
                    sequence_order=seq,
                )
            )

        if not approvals:
            admin = self.db.query(User).filter(User.is_admin.is_(True)).first()
            if admin:
                approvals.append(
                    ClaimApproval(
                        claim_id=claim.id,
                        approver_id=admin.id,
                        approval_level=ApprovalLevel.MANAGER,
                        sequence_order=1,
                    )
                )

        for row in approvals:
            self.db.add(row)
        self.db.flush()
        return approvals

    def _create_linked_expense(
        self,
        claim: Claim,
        user_id: int,
        *,
        transaction_type: TransactionType,
        amount: float,
        status: ExpenseStatus,
        description: str,
        file_data: Optional[bytes] = None,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        mime_type: Optional[str] = None,
        ocr_data: Optional[dict] = None,
        tax_lines: Optional[List[dict]] = None,
        subtotal: Optional[float] = None,
        payment_method: Optional[str] = None,
    ) -> Expense:
        policy = claim.policy
        main_cat = self.policy_service.expense_category_for_policy(policy)
        if claim.main_category and claim.main_category != MainCategory.POLICY:
            main_cat = claim.main_category

        ocr = ocr_data if ocr_data is not None else (claim.ocr_data or {})
        expense = Expense(
            user_id=user_id,
            bill_name=claim.bill_name,
            bill_amount=amount,
            bill_date=claim.bill_date,
            transaction_type=transaction_type,
            main_category=main_cat,
            sub_category=claim.sub_category,
            description=description,
            vendor_name=claim.vendor_name,
            bill_number=claim.bill_number,
            status=status,
            upload_method=UploadMethod.OCR if claim.is_ocr_created else UploadMethod.MANUAL,
            claim_id=claim.id,
            file_data=file_data,
            file_name=file_name,
            file_size=file_size,
            mime_type=mime_type,
            approved_at=datetime.utcnow() if status == ExpenseStatus.APPROVED else None,
            country_code=policy.country_code or "IN",
            subtotal=subtotal,
            payment_method=parse_payment_method(
                payment_method
                or (
                    claim.payment_method.value
                    if claim.payment_method
                    else None
                )
            ),
        )
        self.db.add(expense)
        self.db.flush()

        parsed_lines = tax_lines
        if not parsed_lines and isinstance(ocr.get("tax_payload"), dict):
            parsed_lines = ocr["tax_payload"].get("tax_lines")
            if ocr["tax_payload"].get("subtotal") and subtotal is None:
                subtotal = ocr["tax_payload"].get("subtotal")

        apply_policy_taxes_to_expense(
            self.db,
            expense,
            policy,
            ocr_data=ocr,
            tax_lines=parsed_lines,
            subtotal=subtotal,
        )
        self.db.flush()
        return expense

    def submit_claim(
        self,
        *,
        user_id: int,
        policy: Policy,
        bill_name: str,
        bill_amount: float,
        bill_date: datetime,
        main_category: MainCategory,
        sub_category: Optional[str] = None,
        description: Optional[str] = None,
        bill_number: Optional[str] = None,
        vendor_name: Optional[str] = None,
        file_data: Optional[bytes] = None,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        mime_type: Optional[str] = None,
        ocr_data: Optional[dict] = None,
        is_ocr_created: bool = False,
        tax_lines: Optional[List[dict]] = None,
        subtotal: Optional[float] = None,
        payment_method: Optional[str] = None,
    ) -> Tuple[Claim, Dict[str, Any]]:
        resolved_payment = self.policy_service.resolve_payment_method(
            policy, payment_method
        )

        tax_payload = merge_claim_tax_payload(
            policy,
            ocr_data=ocr_data,
            tax_lines=tax_lines,
            subtotal=subtotal,
        )
        if ocr_data is None:
            ocr_data = {}
        ocr_data = {**ocr_data, "tax_payload": tax_payload}

        validation = self.validate_claim_against_policy(bill_amount, policy)
        if not validation["is_valid"]:
            raise ValueError(validation["reason"])

        over_limit = self.exceeds_policy_limit(bill_amount, policy)
        claim_number = self._generate_claim_number()

        if over_limit:
            claim = Claim(
                claim_number=claim_number,
                policy_id=policy.id,
                user_id=user_id,
                bill_name=bill_name,
                bill_amount=bill_amount,
                bill_date=bill_date,
                claimed_amount=bill_amount,
                approved_amount=0.0,
                main_category=main_category,
                sub_category=sub_category,
                description=description,
                bill_number=bill_number,
                vendor_name=vendor_name,
                status=ClaimStatus.REJECTED,
                rejection_reason=(
                    f"Bill amount {bill_amount} exceeds policy maximum "
                    f"{policy.maximum_amount}. Not eligible for reimbursement."
                ),
                is_reimbursable=False,
                deduction_reason=f"Exceeds policy limit ({policy.maximum_amount})",
                file_data=file_data,
                file_name=file_name,
                file_size=file_size,
                mime_type=mime_type,
                ocr_data=ocr_data,
                is_ocr_created=is_ocr_created,
                payment_method=parse_payment_method(resolved_payment),
            )
            self.db.add(claim)
            self.db.flush()

            expense = self._create_linked_expense(
                claim,
                user_id,
                transaction_type=TransactionType.EXPENSE,
                amount=bill_amount,
                status=ExpenseStatus.APPROVED,
                description=(
                    f"Personal expense (policy claim rejected): {claim.rejection_reason}"
                ),
                file_data=file_data,
                file_name=file_name,
                file_size=file_size,
                mime_type=mime_type,
                ocr_data=ocr_data,
                tax_lines=tax_lines,
                subtotal=subtotal,
                payment_method=resolved_payment,
            )
            WalletService(self.db).update_wallet_balance(user_id, expense)

            meta = {
                "outcome": "rejected_over_limit",
                "message": claim.rejection_reason,
                "linked_expense_id": expense.id,
                "transaction_type": TransactionType.EXPENSE.value,
                "tax_payload": tax_payload,
            }
            return claim, meta

        approved_amount = self.calculate_approved_amount(bill_amount, policy)
        claim = Claim(
            claim_number=claim_number,
            policy_id=policy.id,
            user_id=user_id,
            bill_name=bill_name,
            bill_amount=bill_amount,
            bill_date=bill_date,
            claimed_amount=bill_amount,
            approved_amount=approved_amount,
            main_category=main_category,
            sub_category=sub_category,
            description=description,
            bill_number=bill_number,
            vendor_name=vendor_name,
            status=ClaimStatus.PENDING,
            is_reimbursable=True,
            file_data=file_data,
            file_name=file_name,
            file_size=file_size,
            mime_type=mime_type,
            ocr_data=ocr_data,
            is_ocr_created=is_ocr_created,
            payment_method=parse_payment_method(resolved_payment),
        )
        if approved_amount < bill_amount:
            claim.deduction_reason = f"Capped at policy maximum {policy.maximum_amount}"

        self.db.add(claim)
        self.db.flush()
        self.create_approval_workflow(claim, policy)

        meta = {
            "outcome": "pending_approval",
            "message": (
                "Claim submitted within policy limit. "
                "Awaiting department head and manager approval."
            ),
            "linked_expense_id": None,
            "transaction_type": None,
            "tax_payload": tax_payload,
        }
        return claim, meta

    def _prior_approvals_complete(self, claim_id: int, sequence_order: int) -> bool:
        prior = (
            self.db.query(ClaimApproval)
            .filter(
                ClaimApproval.claim_id == claim_id,
                ClaimApproval.sequence_order < sequence_order,
            )
            .all()
        )
        return all(a.status == ApprovalStatus.APPROVED for a in prior)

    def can_approver_act(self, approval: ClaimApproval) -> bool:
        if approval.status != ApprovalStatus.PENDING:
            return False
        return self._prior_approvals_complete(approval.claim_id, approval.sequence_order)

    def process_approval(
        self,
        approval_id: int,
        approver_id: int,
        status: ApprovalStatus,
        comments: Optional[str] = None,
        approved_amount: Optional[float] = None,
    ) -> ClaimApproval:
        approval = (
            self.db.query(ClaimApproval)
            .filter(
                ClaimApproval.id == approval_id,
                ClaimApproval.approver_id == approver_id,
            )
            .first()
        )
        if not approval:
            raise ValueError("Approval not found or not authorized")

        if not self.can_approver_act(approval):
            raise ValueError("Previous approval step must be completed first")

        claim = approval.claim
        if claim.status != ClaimStatus.PENDING:
            raise ValueError(f"Claim is already {claim.status.value}")

        approval.status = status
        approval.comments = comments
        approval.actioned_at = datetime.utcnow()
        if approved_amount is not None:
            approval.approved_amount = approved_amount

        if status == ApprovalStatus.REJECTED:
            claim.status = ClaimStatus.REJECTED
            claim.rejection_reason = comments or "Rejected by approver"
            claim.is_reimbursable = False
            expense = self._create_linked_expense(
                claim,
                claim.user_id,
                transaction_type=TransactionType.EXPENSE,
                amount=claim.bill_amount,
                status=ExpenseStatus.APPROVED,
                description=f"Expense after claim rejection: {claim.rejection_reason}",
                ocr_data=claim.ocr_data,
            )
            WalletService(self.db).update_wallet_balance(claim.user_id, expense)
            self.db.flush()
            return approval

        pending = (
            self.db.query(ClaimApproval)
            .filter(
                ClaimApproval.claim_id == claim.id,
                ClaimApproval.status == ApprovalStatus.PENDING,
            )
            .count()
        )
        if pending == 0:
            self._finalize_approved_claim(claim)

        self.db.flush()
        return approval

    def _finalize_approved_claim(self, claim: Claim) -> None:
        claim.status = ClaimStatus.APPROVED
        claim.approved_at = datetime.utcnow()
        if not claim.approved_amount:
            claim.approved_amount = self.calculate_approved_amount(
                claim.claimed_amount, claim.policy
            )

        expense = self._create_linked_expense(
            claim,
            claim.user_id,
            transaction_type=TransactionType.INCOME,
            amount=claim.approved_amount,
            status=ExpenseStatus.APPROVED,
            description=f"Policy reimbursement (approved): {claim.claim_number}",
            ocr_data=claim.ocr_data,
        )
        claim.reimbursed_amount = claim.approved_amount
        claim.status = ClaimStatus.REIMBURSED
        claim.reimbursed_at = datetime.utcnow()
        WalletService(self.db).update_wallet_balance(claim.user_id, expense)

    def get_claim_summary(self, user_id: int) -> Dict[str, Any]:
        claims = self.db.query(Claim).filter(Claim.user_id == user_id).all()
        return {
            "total_claims": len(claims),
            "pending_claims": len([c for c in claims if c.status == ClaimStatus.PENDING]),
            "approved_claims": len([c for c in claims if c.status == ClaimStatus.APPROVED]),
            "rejected_claims": len([c for c in claims if c.status == ClaimStatus.REJECTED]),
            "reimbursed_claims": len(
                [c for c in claims if c.status == ClaimStatus.REIMBURSED]
            ),
            "total_claimed_amount": sum(c.claimed_amount for c in claims),
            "total_approved_amount": sum(
                c.approved_amount
                for c in claims
                if c.status in (ClaimStatus.APPROVED, ClaimStatus.REIMBURSED)
            ),
            "total_reimbursed_amount": sum(
                c.reimbursed_amount for c in claims if c.status == ClaimStatus.REIMBURSED
            ),
            "eligible_for_reimbursement": len(
                [c for c in claims if c.is_reimbursable and c.status == ClaimStatus.PENDING]
            ),
            "rejected_over_limit": len(
                [
                    c
                    for c in claims
                    if c.status == ClaimStatus.REJECTED
                    and c.rejection_reason
                    and "exceeds policy maximum" in (c.rejection_reason or "").lower()
                ]
            ),
        }

    def get_claim_approval_status(self, claim_id: int) -> Dict[str, Any]:
        approvals = (
            self.db.query(ClaimApproval)
            .filter(ClaimApproval.claim_id == claim_id)
            .order_by(ClaimApproval.sequence_order.asc())
            .all()
        )
        return {
            "claim_id": claim_id,
            "total_approvals": len(approvals),
            "completed_approvals": len(
                [a for a in approvals if a.status != ApprovalStatus.PENDING]
            ),
            "pending_approvals": len(
                [a for a in approvals if a.status == ApprovalStatus.PENDING]
            ),
            "approval_details": approvals,
        }

    def get_claim(self, claim_id: int) -> Optional[Claim]:
        return (
            self.db.query(Claim)
            .options(joinedload(Claim.approvals), joinedload(Claim.policy))
            .filter(Claim.id == claim_id)
            .first()
        )

    def require_claim(self, claim_id: int) -> Claim:
        claim = self.get_claim(claim_id)
        if not claim:
            raise ValueError("Claim not found")
        return claim

    def user_can_view_claim(self, claim: Claim, user: User) -> bool:
        if claim.user_id == user.id or user.is_admin:
            return True
        from app.models import ClaimApproval

        return (
            self.db.query(ClaimApproval)
            .filter(
                ClaimApproval.claim_id == claim.id,
                ClaimApproval.approver_id == user.id,
            )
            .first()
            is not None
        )

    def get_claim_for_viewer(self, claim_id: int, user: User) -> Claim:
        claim = self.require_claim(claim_id)
        if not self.user_can_view_claim(claim, user):
            raise ValueError("Permission denied")
        return claim

    def list_user_claims(
        self,
        user_id: int,
        *,
        status_filter: Optional[ClaimStatus] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Claim]:
        query = (
            self.db.query(Claim)
            .options(joinedload(Claim.approvals), joinedload(Claim.policy))
            .filter(Claim.user_id == user_id)
        )
        if status_filter:
            query = query.filter(Claim.status == status_filter)
        return query.order_by(Claim.submitted_at.desc()).offset(skip).limit(limit).all()

    def list_pending_for_approver(self, approver_id: int) -> List[Claim]:
        from app.models import ClaimApproval, ApprovalStatus

        approvals = (
            self.db.query(ClaimApproval)
            .filter(
                ClaimApproval.approver_id == approver_id,
                ClaimApproval.status == ApprovalStatus.PENDING,
            )
            .all()
        )
        claims: List[Claim] = []
        for approval in approvals:
            if self.can_approver_act(approval):
                claim = self.require_claim(approval.claim_id)
                claims.append(claim)
        return claims
