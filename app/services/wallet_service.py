from sqlalchemy.orm import Session
from app.models import Wallet, WalletTransaction, Expense, TransactionType, ExpenseStatus
from app.deps.scope import ExpenseScope
from app.services.expense_scope_service import wallet_owner_clause
from datetime import datetime

class WalletService:
    def __init__(self, db: Session):
        self.db = db
    
    def get_or_create_wallet(
        self,
        user_id: int,
        company_id: int = 1,
        currency: str | None = None,
    ) -> Wallet:
        """Get user's wallet or create if doesn't exist (scoped by company + user)."""
        scope = ExpenseScope(user_id=user_id, company_id=company_id, currency=currency)
        wallet = self.db.query(Wallet).filter(wallet_owner_clause(scope)).first()
        if not wallet:
            now = datetime.utcnow()
            wallet = Wallet(
                user_id=user_id,
                company_id=company_id,
                balance=0.0,
                total_income=0.0,
                total_expense=0.0,
                updated_at=now,
            )
            self.db.add(wallet)
            self.db.commit()
            self.db.refresh(wallet)
        return wallet

    def get_or_create_wallet_for_scope(self, scope: ExpenseScope) -> Wallet:
        return self.get_or_create_wallet(
            scope.user_id, scope.company_id, scope.currency
        )
    
    def update_wallet_balance(self, user_id: int, expense: Expense):
        """Update wallet balance when expense is approved."""
        company_id = getattr(expense, "company_id", None) or 1
        wallet = self.get_or_create_wallet(user_id, company_id)
        
        # Check if already processed
        existing_transaction = self.db.query(WalletTransaction).filter(
            WalletTransaction.expense_id == expense.id
        ).first()
        
        if existing_transaction:
            return wallet
        
        # Update wallet based on transaction type
        if expense.transaction_type == TransactionType.INCOME:
            wallet.balance += expense.bill_amount
            wallet.total_income += expense.bill_amount
        else:  # EXPENSE
            if wallet.balance >= expense.bill_amount:
                wallet.balance -= expense.bill_amount
            else:
                # Handle insufficient balance (could set negative or raise error)
                wallet.balance -= expense.bill_amount
            wallet.total_expense += expense.bill_amount
        
        wallet.updated_at = datetime.utcnow()
        
        # Create transaction record
        transaction = WalletTransaction(
            wallet_id=wallet.id,
            expense_id=expense.id,
            amount=expense.bill_amount,
            transaction_type=expense.transaction_type,
            description=f"{expense.bill_name} - {expense.main_category.value}",
            main_category=expense.main_category,
            sub_category=expense.sub_category,
        )
        
        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(wallet)
        
        return wallet
    
    def revert_transaction(self, expense_id: int):
        """Revert wallet transaction (if expense is rejected or deleted)"""
        transaction = self.db.query(WalletTransaction).filter(
            WalletTransaction.expense_id == expense_id
        ).first()
        
        if not transaction:
            return
        
        wallet = self.db.query(Wallet).filter(Wallet.id == transaction.wallet_id).first()
        
        # Reverse the transaction
        if transaction.transaction_type == TransactionType.INCOME:
            wallet.balance -= transaction.amount
            wallet.total_income -= transaction.amount
        else:
            wallet.balance += transaction.amount
            wallet.total_expense -= transaction.amount
        
        # Delete transaction record
        self.db.delete(transaction)
        self.db.commit()
