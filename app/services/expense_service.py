# services/expense_service.py
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from fastapi import HTTPException, status

from app.models import (
    Expense, User, Wallet, WalletTransaction, OCRBill,
    ExpenseStatus, TransactionType, MainCategory, UploadMethod, PaymentMethod,
)
from app.utils.category_hashtags import (
    default_expense_hashtags,
    normalize_hashtags_list,
)
from app.utils.expense_helpers import parse_payment_method
from app.utils.expense_validation import (
    assert_expense_editable,
    draft_has_minimum_fields,
    is_awaiting_approval,
    validate_expense_date_not_future,
    validate_required_draft_fields,
)
from app.schemas import ExpenseCreate, ExpenseSubmit, ExpenseUpdate
from app.services.tax_service import TaxService
from app.services.wallet_service import WalletService

class ExpenseService:
    """Service class for handling expense-related business logic"""
    
    def __init__(self, db: Session):
        self.db = db
    
    @staticmethod
    def create_expense(
        db: Session,
        expense_data: ExpenseCreate,
        user_id: int,
        upload_method: UploadMethod,
        status: ExpenseStatus = ExpenseStatus.PENDING,
    ) -> Expense:
        """Create a new expense entry"""
        
        # Validate amount for expense type
        if expense_data.transaction_type == TransactionType.EXPENSE and expense_data.bill_amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Expense amount must be greater than 0"
            )
        
        # Validate date is not in future
        validate_expense_date_not_future(expense_data.bill_date)

        explicit_tags = normalize_hashtags_list(
            getattr(expense_data, "hashtags", None) or []
        )
        if not explicit_tags:
            explicit_tags = default_expense_hashtags(
                expense_data.main_category.value,
                expense_data.sub_category,
                vendor_name=expense_data.vendor_name,
                bill_name=expense_data.bill_name,
            )

        # Create expense object
        expense = Expense(
            user_id=user_id,
            bill_name=expense_data.bill_name,
            bill_amount=expense_data.bill_amount,
            bill_date=expense_data.bill_date,
            transaction_type=expense_data.transaction_type,
            main_category=expense_data.main_category,
            sub_category=expense_data.sub_category,
            description=expense_data.description,
            payment_method=parse_payment_method(expense_data.payment_method),
            vendor_name=expense_data.vendor_name,
            bill_number=expense_data.bill_number,
            tax_amount=expense_data.tax_amount or 0.0,
            discount_amount=expense_data.discount_amount or 0.0,
            upload_method=upload_method,
            status=status,
            hashtags=explicit_tags,
            line_item=getattr(expense_data, "line_item", None),
            submitted_by_name=(getattr(expense_data, "submitted_by_name", None) or "").strip() or None,
            submitted_by_role=(getattr(expense_data, "submitted_by_role", None) or "").strip() or None,
        )
        from app.utils.expense_business_fields import apply_business_fields

        apply_business_fields(
            expense,
            main_category=expense_data.main_category,
            sub_category=expense_data.sub_category,
            line_item=getattr(expense_data, "line_item", None),
            bill_date=expense_data.bill_date,
            currency_code=getattr(expense_data, "currency_code", None),
            vendor_name=expense_data.vendor_name,
        )

        db.add(expense)
        db.commit()
        db.refresh(expense)
        
        return expense
    
    def get_expense(self, expense_id: int, user_id: int) -> Optional[Expense]:
        """Get a single expense by ID"""
        return (
            self.db.query(Expense)
            .options(joinedload(Expense.files), joinedload(Expense.tax_lines))
            .filter(Expense.id == expense_id, Expense.user_id == user_id)
            .first()
        )
    
    def get_user_expenses(
        self,
        user_id: int,
        status: Optional[ExpenseStatus] = None,
        statuses: Optional[List[ExpenseStatus]] = None,
        main_category: Optional[MainCategory] = None,
        sub_category: Optional[str] = None,
        transaction_type: Optional[TransactionType] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search_term: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        upload_method: Optional[str] = None,
        hashtag: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Tuple[List[Expense], int]:
        """Get user's expenses with filters and pagination"""
        
        query = (
            self.db.query(Expense)
            .options(joinedload(Expense.files), joinedload(Expense.tax_lines))
            .filter(Expense.user_id == user_id)
        )

        if statuses:
            query = query.filter(Expense.status.in_(statuses))
        elif status:
            query = query.filter(Expense.status == status)

        if main_category:
            query = query.filter(Expense.main_category == main_category)

        if sub_category:
            query = query.filter(Expense.sub_category == sub_category)
        
        if transaction_type:
            query = query.filter(Expense.transaction_type == transaction_type)
        
        if start_date:
            query = query.filter(Expense.bill_date >= start_date)
        
        if end_date:
            query = query.filter(Expense.bill_date <= end_date)

        if min_amount is not None:
            query = query.filter(Expense.bill_amount >= min_amount)

        if max_amount is not None:
            query = query.filter(Expense.bill_amount <= max_amount)

        if upload_method:
            query = query.filter(Expense.upload_method == upload_method)

        if hashtag:
            tag = hashtag.lstrip("#").lower()
            query = query.filter(Expense.hashtags.contains([tag]))
        
        if search_term:
            query = query.filter(
                or_(
                    Expense.bill_name.ilike(f"%{search_term}%"),
                    Expense.vendor_name.ilike(f"%{search_term}%"),
                    Expense.description.ilike(f"%{search_term}%"),
                    Expense.bill_number.ilike(f"%{search_term}%")
                )
            )
        
        # Get total count for pagination
        total_count = query.count()
        
        # Get paginated results
        expenses = query.order_by(
            Expense.bill_date.desc()
        ).offset(skip).limit(limit).all()
        
        return expenses, total_count
    
    def update_expense(
        self,
        expense_id: int,
        user_id: int,
        expense_update: ExpenseUpdate
    ) -> Expense:
        """Update an existing expense"""
        
        expense = self.get_expense(expense_id, user_id)
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found"
            )
        
        assert_expense_editable(expense)
        
        old_status = expense.status

        # Update fields
        update_data = expense_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            if field == "payment_method":
                setattr(expense, field, parse_payment_method(value))
            elif field == "hashtags" and value is not None:
                expense.hashtags = normalize_hashtags_list(value)
            elif field == "tax_lines" and value is not None:
                TaxService(self.db).replace_expense_taxes(
                    expense,
                    [line.model_dump() for line in value],
                )
            elif field == "country_code":
                continue  # country selection removed from UI
            elif field == "transaction_type":
                continue  # expense-only tracker
            elif field == "bill_date" and value is not None:
                expense.bill_date = validate_expense_date_not_future(value)
            elif field in ("payment_method", "payment_mode") and value is not None:
                expense.payment_method = parse_payment_method(value)
            else:
                setattr(expense, field, value)

        if expense.status == ExpenseStatus.DRAFT:
            validate_required_draft_fields(
                bill_name=expense.bill_name,
                bill_amount=expense.bill_amount,
                main_category=expense.main_category,
            )

        if not normalize_hashtags_list(expense.hashtags or []):
            expense.hashtags = default_expense_hashtags(
                expense.main_category.value if expense.main_category else "miscellaneous",
                expense.sub_category,
                vendor_name=expense.vendor_name,
                bill_name=expense.bill_name,
            )

        expense.updated_at = datetime.utcnow()

        new_status = expense.status
        if new_status == ExpenseStatus.APPROVED and old_status != ExpenseStatus.APPROVED:
            if not expense.approved_at:
                expense.approved_at = datetime.utcnow()
            WalletService(self.db).update_wallet_balance(user_id, expense)
        elif old_status == ExpenseStatus.APPROVED and new_status != ExpenseStatus.APPROVED:
            WalletService(self.db).revert_transaction(expense.id)
            expense.approved_at = None

        self.db.commit()
        self.db.refresh(expense)

        return expense
    
    def delete_expense(self, expense_id: int, user_id: int) -> bool:
        """Delete an expense (not allowed for approved bills)."""

        expense = self.get_expense(expense_id, user_id)
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found",
            )

        from app.utils.expense_validation import assert_expense_deletable

        assert_expense_deletable(expense)

        self.db.delete(expense)
        self.db.commit()

        return True
    
    def update_expense_status(
        self,
        expense_id: int,
        user_id: int,
        new_status: ExpenseStatus,
        rejection_reason: Optional[str] = None,
        approver_id: Optional[int] = None
    ) -> Expense:
        """Update expense status (approve/reject)"""
        
        expense = self.get_expense(expense_id, user_id)
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found"
            )
        
        # Only submitted/pending expenses can be approved/rejected
        if not is_awaiting_approval(expense.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot change status from {expense.status} to {new_status}"
            )
        
        old_status = expense.status
        expense.status = new_status
        
        if new_status == ExpenseStatus.APPROVED:
            expense.approved_at = datetime.utcnow()
            expense.rejection_reason = None
        elif new_status == ExpenseStatus.REJECTED:
            expense.rejection_reason = rejection_reason
            expense.approved_at = None
        
        expense.updated_at = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(expense)
        
        # If approved, update wallet
        if new_status == ExpenseStatus.APPROVED and old_status != ExpenseStatus.APPROVED:
            from app.services.wallet_service import WalletService
            wallet_service = WalletService(self.db)
            wallet_service.update_wallet_balance(user_id, expense)
        
        return expense

    def submit_for_approval(self, expense_id: int, user_id: int) -> Expense:
        """Move draft or legacy pending expense to submitted (awaiting approval)."""
        expense = self.get_expense(expense_id, user_id)
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found",
            )
        if expense.status not in (
            ExpenseStatus.DRAFT,
            ExpenseStatus.PENDING,
            ExpenseStatus.REJECTED,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot submit expense in status {expense.status.value}",
            )
        if expense.status == ExpenseStatus.REJECTED:
            if not draft_has_minimum_fields(expense):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Rejected expense is missing required fields before resubmit",
                )
        expense.status = ExpenseStatus.SUBMITTED
        expense.rejection_reason = None
        expense.updated_at = datetime.utcnow()
        from app.services.expense_approval_service import create_expense_approval_workflow

        create_expense_approval_workflow(self.db, expense)
        self.db.commit()
        self.db.refresh(expense)
        return expense
    
    def get_expense_summary(
        self,
        user_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get summary statistics for expenses"""
        
        query = self.db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.status == ExpenseStatus.APPROVED
        )
        
        if start_date:
            query = query.filter(Expense.bill_date >= start_date)
        if end_date:
            query = query.filter(Expense.bill_date <= end_date)
        
        expenses = query.all()
        
        # Calculate totals
        total_income = sum(e.bill_amount for e in expenses if e.transaction_type == TransactionType.INCOME)
        total_expense = sum(e.bill_amount for e in expenses if e.transaction_type == TransactionType.EXPENSE)
        net_savings = total_income - total_expense
        
        # Group by category
        category_breakdown = {}
        for expense in expenses:
            if expense.transaction_type == TransactionType.EXPENSE:
                category_name = expense.main_category.value
                if category_name not in category_breakdown:
                    category_breakdown[category_name] = {
                        "total": 0,
                        "count": 0,
                        "average": 0
                    }
                category_breakdown[category_name]["total"] += expense.bill_amount
                category_breakdown[category_name]["count"] += 1
        
        # Calculate averages
        for category in category_breakdown:
            category_breakdown[category]["average"] = (
                category_breakdown[category]["total"] / category_breakdown[category]["count"]
                if category_breakdown[category]["count"] > 0 else 0
            )
        
        return {
            "total_income": total_income,
            "total_expense": total_expense,
            "net_savings": net_savings,
            "transaction_count": len(expenses),
            "category_breakdown": category_breakdown,
            "average_transaction": total_expense / len([e for e in expenses if e.transaction_type == TransactionType.EXPENSE])
            if len([e for e in expenses if e.transaction_type == TransactionType.EXPENSE]) > 0 else 0
        }
    
    def get_pending_expenses(self, user_id: int) -> List[Expense]:
        """Get all expenses awaiting approval (submitted or legacy pending)."""
        return self.db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.status.in_([ExpenseStatus.SUBMITTED, ExpenseStatus.PENDING])
        ).order_by(Expense.bill_date.asc()).all()
    
    def get_draft_expenses(self, user_id: int) -> List[Expense]:
        """Get all draft expenses for a user"""
        return self.db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.status == ExpenseStatus.DRAFT
        ).order_by(Expense.updated_at.desc()).all()
    
    def submit_draft(
        self,
        expense_id: int,
        user_id: int,
        data: ExpenseSubmit,
    ) -> Expense:
        """Save draft fields; with confirm_submit move to submitted (awaiting approval)."""
        expense = self.get_expense(expense_id, user_id)
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found",
            )
        if expense.status not in (ExpenseStatus.DRAFT, ExpenseStatus.REJECTED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only draft or rejected expenses can be submitted (current: {expense.status})",
            )

        validate_expense_date_not_future(data.bill_date)
        validate_required_draft_fields(
            bill_name=data.bill_name,
            bill_amount=data.bill_amount,
            main_category=data.main_category,
        )

        expense.bill_name = data.bill_name
        expense.bill_amount = data.bill_amount
        expense.bill_date = data.bill_date
        expense.transaction_type = TransactionType.EXPENSE
        expense.main_category = data.main_category
        expense.sub_category = data.sub_category
        expense.line_item = getattr(data, "line_item", None) or expense.line_item
        expense.description = data.description
        expense.vendor_name = data.vendor_name
        expense.bill_number = data.bill_number
        if getattr(data, "submitted_by_name", None) is not None:
            expense.submitted_by_name = (data.submitted_by_name or "").strip() or None
        if getattr(data, "submitted_by_role", None) is not None:
            expense.submitted_by_role = (data.submitted_by_role or "").strip() or None
        expense.tax_amount = data.tax_amount or 0.0
        expense.discount_amount = data.discount_amount or 0.0
        expense.payment_method = parse_payment_method(data.payment_method)
        if data.hashtags is not None:
            expense.hashtags = normalize_hashtags_list(data.hashtags)
        if data.subtotal is not None:
            expense.subtotal = data.subtotal
        if data.tax_lines is not None:
            TaxService(self.db).replace_expense_taxes(
                expense,
                [line.model_dump() for line in data.tax_lines],
            )
        pm = data.payment_method or data.payment_mode
        if pm is not None:
            expense.payment_method = parse_payment_method(pm)

        if data.auto_approve:
            expense.status = ExpenseStatus.APPROVED
            expense.approved_at = datetime.utcnow()
            expense.rejection_reason = None
        elif data.save_as_draft:
            expense.status = ExpenseStatus.DRAFT
        else:
            expense.status = ExpenseStatus.SUBMITTED
            expense.rejection_reason = None
            from app.services.expense_approval_service import create_expense_approval_workflow

            create_expense_approval_workflow(self.db, expense)

        from app.utils.expense_business_fields import apply_business_fields

        apply_business_fields(
            expense,
            main_category=data.main_category,
            sub_category=data.sub_category,
            line_item=getattr(data, "line_item", None),
            bill_date=data.bill_date,
            amount_excl_gst=getattr(data, "amount_excl_gst", None),
            gst_rate_pct=getattr(data, "gst_rate_pct", None),
            gst_amount=getattr(data, "gst_amount", None),
            itc_eligible=getattr(data, "itc_eligible", None),
            currency_code=getattr(data, "currency_code", None),
            vendor_name=data.vendor_name,
        )

        expense.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(expense)

        if expense.status == ExpenseStatus.APPROVED:
            WalletService(self.db).update_wallet_balance(user_id, expense)

        return expense

    def discard_incomplete_draft(self, expense_id: int, user_id: int) -> bool:
        """Delete draft if minimum required fields are not filled."""
        expense = self.get_expense(expense_id, user_id)
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found",
            )
        if expense.status != ExpenseStatus.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft expenses can be discarded",
            )
        if draft_has_minimum_fields(expense):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Draft has required fields filled. Save as draft or submit instead of discarding.",
            )
        self.db.delete(expense)
        self.db.commit()
        return True

    def complete_draft(
        self,
        expense_id: int,
        user_id: int,
        complete_data: ExpenseCreate
    ) -> Expense:
        """Complete a draft expense and move to pending"""
        
        expense = self.get_expense(expense_id, user_id)
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found"
            )
        
        if expense.status != ExpenseStatus.DRAFT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot complete expense with status: {expense.status}"
            )
        
        # Update expense with complete data
        update_data = complete_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(expense, field, value)
        
        expense.status = ExpenseStatus.SUBMITTED
        expense.updated_at = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(expense)
        
        return expense
    
    def bulk_create_expenses(
        self,
        expenses_data: List[ExpenseCreate],
        user_id: int,
        upload_method: UploadMethod = UploadMethod.MANUAL
    ) -> List[Expense]:
        """Create multiple expenses at once"""
        
        created_expenses = []
        for expense_data in expenses_data:
            expense = self.create_expense(
                db=self.db,
                expense_data=expense_data,
                user_id=user_id,
                upload_method=upload_method,
                status=ExpenseStatus.SUBMITTED
            )
            created_expenses.append(expense)
        
        return created_expenses
    
    def get_expenses_by_date_range(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        status: Optional[ExpenseStatus] = ExpenseStatus.APPROVED
    ) -> List[Expense]:
        """Get expenses within a date range"""
        
        return self.db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.status == status,
            Expense.bill_date.between(start_date, end_date)
        ).order_by(Expense.bill_date).all()
    
    def get_top_spending_categories(
        self,
        user_id: int,
        limit: int = 5,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """Get top spending categories for last N days"""
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        results = self.db.query(
            Expense.main_category,
            func.sum(Expense.bill_amount).label('total'),
            func.count(Expense.id).label('count')
        ).filter(
            Expense.user_id == user_id,
            Expense.status == ExpenseStatus.APPROVED,
            Expense.transaction_type == TransactionType.EXPENSE,
            Expense.bill_date >= start_date
        ).group_by(
            Expense.main_category
        ).order_by(
            func.sum(Expense.bill_amount).desc()
        ).limit(limit).all()
        
        return [
            {
                "category": result.main_category.value,
                "total_amount": float(result.total),
                "transaction_count": result.count,
                "average_amount": float(result.total) / result.count if result.count > 0 else 0
            }
            for result in results
        ]
    
    def search_expenses(
        self,
        user_id: int,
        query: str,
        limit: int = 20
    ) -> List[Expense]:
        """Search expenses by name, vendor, or description"""
        
        return self.db.query(Expense).filter(
            Expense.user_id == user_id,
            or_(
                Expense.bill_name.ilike(f"%{query}%"),
                Expense.vendor_name.ilike(f"%{query}%"),
                Expense.description.ilike(f"%{query}%"),
                Expense.bill_number.ilike(f"%{query}%")
            )
        ).order_by(Expense.bill_date.desc()).limit(limit).all()
    
    def get_monthly_trend(
        self,
        user_id: int,
        months: int = 6
    ) -> List[Dict[str, Any]]:
        """Get monthly income/expense trend"""
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30 * months)
        
        results = self.db.query(
            func.date_trunc('month', Expense.bill_date).label('month'),
            Expense.transaction_type,
            func.sum(Expense.bill_amount).label('total')
        ).filter(
            Expense.user_id == user_id,
            Expense.status == ExpenseStatus.APPROVED,
            Expense.bill_date.between(start_date, end_date)
        ).group_by(
            'month', Expense.transaction_type
        ).order_by('month').all()
        
        # Organize by month
        monthly_data = {}
        for result in results:
            month_key = result.month.strftime('%Y-%m')
            if month_key not in monthly_data:
                monthly_data[month_key] = {'income': 0, 'expense': 0, 'month': month_key}
            
            if result.transaction_type == TransactionType.INCOME:
                monthly_data[month_key]['income'] = float(result.total)
            else:
                monthly_data[month_key]['expense'] = float(result.total)
        
        return list(monthly_data.values())
    
    def validate_expense_limit(
        self,
        user_id: int,
        main_category: MainCategory,
        amount: float,
        monthly_limit: Optional[float] = None
    ) -> bool:
        """Check if expense exceeds monthly limit for category"""
        
        if not monthly_limit:
            return True
        
        # Get current month's expenses for this category
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        total_this_month = self.db.query(func.sum(Expense.bill_amount)).filter(
            Expense.user_id == user_id,
            Expense.main_category == category,
            Expense.transaction_type == TransactionType.EXPENSE,
            Expense.status == ExpenseStatus.APPROVED,
            Expense.bill_date >= current_month_start
        ).scalar() or 0
        
        # Check if adding this expense would exceed limit
        return (total_this_month + amount) <= monthly_limit
    
    def get_duplicate_expenses(
        self,
        user_id: int,
        expense_data: ExpenseCreate,
        days_window: int = 1
    ) -> List[Expense]:
        """Check for potential duplicate expenses within time window"""
        
        start_date = expense_data.bill_date - timedelta(days=days_window)
        end_date = expense_data.bill_date + timedelta(days=days_window)
        
        # Find expenses with similar amount and vendor
        potential_duplicates = self.db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.bill_amount == expense_data.bill_amount,
            Expense.vendor_name == expense_data.vendor_name,
            Expense.bill_date.between(start_date, end_date),
            Expense.status != ExpenseStatus.REJECTED
        ).all()
        
        return potential_duplicates
    
    def archive_old_expenses(self, user_id: int, days: int = 365) -> int:
        """Archive expenses older than specified days (soft delete)"""
        
        archive_date = datetime.utcnow() - timedelta(days=days)
        
        # In a real implementation, you might move to an archive table
        # For now, we'll just mark them or delete
        old_expenses = self.db.query(Expense).filter(
            Expense.user_id == user_id,
            Expense.bill_date < archive_date,
            Expense.status == ExpenseStatus.APPROVED
        ).all()
        
        count = len(old_expenses)
        
        # Option 1: Delete them
        for expense in old_expenses:
            self.db.delete(expense)
        
        # Option 2: Mark as archived (if you add an is_archived column)
        # for expense in old_expenses:
        #     expense.is_archived = True
        
        self.db.commit()
        
        return count
    
    def generate_expense_report(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        group_by: str = "category"  # category, day, week, month
    ) -> Dict[str, Any]:
        """Generate detailed expense report"""
        
        expenses = self.get_expenses_by_date_range(user_id, start_date, end_date)
        
        report = {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "summary": {
                "total_income": 0,
                "total_expense": 0,
                "net": 0,
                "total_transactions": len(expenses)
            },
            "breakdown": {},
            "transactions": []
        }
        
        # Calculate totals
        for expense in expenses:
            if expense.transaction_type == TransactionType.INCOME:
                report["summary"]["total_income"] += expense.bill_amount
            else:
                report["summary"]["total_expense"] += expense.bill_amount
            
            # Add to breakdown
            if group_by == "category":
                key = expense.main_category.value
            elif group_by == "day":
                key = expense.bill_date.strftime('%Y-%m-%d')
            elif group_by == "week":
                key = f"Week {expense.bill_date.isocalendar()[1]}"
            else:  # month
                key = expense.bill_date.strftime('%Y-%m')
            
            if key not in report["breakdown"]:
                report["breakdown"][key] = 0
            report["breakdown"][key] += expense.bill_amount
        
        report["summary"]["net"] = report["summary"]["total_income"] - report["summary"]["total_expense"]
        
        # Add transaction details (limit to last 100)
        report["transactions"] = [
            {
                "id": e.id,
                "date": e.bill_date.isoformat(),
                "name": e.bill_name,
                "amount": e.bill_amount,
                "type": e.transaction_type.value,
                "category": e.main_category.value,
                "vendor": e.vendor_name
            }
            for e in expenses[:100]
        ]
        
        return report