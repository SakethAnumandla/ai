# app/dependencies.py
"""
Dependencies for FastAPI routes: database sessions, pagination, and common utilities.
"""

from fastapi import Depends, HTTPException, status, Query, Request, UploadFile
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta
import logging

from app.database import get_db
from app.models import User, ExpenseStatus, MainCategory, TransactionType
from app.utils.transaction_parser import coerce_transaction_type
from app.utils.time_period import (
    ALL_TIME,
    resolve_date_filter,
    resolve_time_period,
    ResolvedTimePeriod,
)

logger = logging.getLogger(__name__)

DEV_USER_EMAIL = "dev@local.test"
DEV_USER_USERNAME = "devuser"


async def get_current_user(db: Session = Depends(get_db)) -> User:
    """Alias for authenticated user (dev: default user)."""
    return await get_default_user(db)


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_default_user(db: Session = Depends(get_db)) -> User:
    """Single dev user for local testing (no login required)."""
    from app.models import UserRole, Department, Wallet

    user = db.query(User).filter(User.username == DEV_USER_USERNAME).first()
    if user:
        # Local dev / Postman: full access for finance, executive, manager APIs
        changed = False
        if not user.is_admin:
            user.is_admin = True
            changed = True
        if user.role not in (
            UserRole.SUPER_ADMIN,
            UserRole.FINANCE_ADMIN,
            UserRole.MANAGER,
            UserRole.DEPARTMENT_HEAD,
        ):
            user.role = UserRole.SUPER_ADMIN
            changed = True
        if changed:
            db.commit()
            db.refresh(user)
        wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
        if not wallet:
            db.add(Wallet(user_id=user.id))
            db.commit()
        return user

    user = User(
        email=DEV_USER_EMAIL,
        username=DEV_USER_USERNAME,
        hashed_password="not-used",
        full_name="Dev User",
        is_active=True,
        is_admin=True,
        role=UserRole.SUPER_ADMIN,
        department=Department.ENGINEERING,
    )
    db.add(user)
    db.flush()
    db.add(Wallet(user_id=user.id))
    db.commit()
    db.refresh(user)
    return user

# ==================== Pagination Dependencies ====================

class PaginationParams:
    """Pagination parameters for list endpoints"""
    
    def __init__(
        self,
        skip: int = Query(0, ge=0, description="Number of records to skip"),
        limit: int = Query(100, ge=1, le=1000, description="Number of records to return"),
        sort_by: Optional[str] = Query(None, description="Field to sort by"),
        sort_desc: bool = Query(False, description="Sort in descending order")
    ):
        self.skip = skip
        self.limit = limit
        self.sort_by = sort_by
        self.sort_desc = sort_desc
    
    def apply_to_query(self, query, model):
        """Apply pagination and sorting to SQLAlchemy query"""
        if self.sort_by and hasattr(model, self.sort_by):
            sort_column = getattr(model, self.sort_by)
            if self.sort_desc:
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        
        return query.offset(self.skip).limit(self.limit)

# ==================== Time period filter ====================


class TimePeriodFilter:
    """
    Shared date filter for dashboard, wallet, and expenses.

    Presets: period=this_month | last_month | this_year | last_year | all_time
    Single day: date=2026-05-15  (or period=date&date=...)
    Date range: start_date=...&end_date=...  (period=custom optional)
    """

    def __init__(
        self,
        period: Optional[str] = Query(
            "this_month",
            description=(
                "Preset: this_month, last_month, this_year, last_year, all_time, "
                "date, custom"
            ),
        ),
        date: Optional[datetime] = Query(
            None,
            description="Single calendar day (custom date picker)",
        ),
        start_date: Optional[datetime] = Query(
            None, description="Custom range start (use with end_date)"
        ),
        end_date: Optional[datetime] = Query(
            None, description="Custom range end (defaults to today if start_date set)"
        ),
    ):
        try:
            self.resolved = resolve_date_filter(
                period=period,
                date=date,
                start_date=start_date,
                end_date=end_date,
                default_period="this_month",
            )
            if self.resolved is None:
                self.resolved = resolve_time_period("this_month")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @property
    def period(self) -> str:
        return self.resolved.period

    @property
    def start_date(self) -> Optional[datetime]:
        return self.resolved.start_date

    @property
    def end_date(self) -> datetime:
        return self.resolved.end_date

    @property
    def is_all_time(self) -> bool:
        return self.resolved.is_all_time

    def as_meta(self) -> dict:
        return self.resolved.as_dict()


class OptionalTimePeriodFilter:
    """Like TimePeriodFilter but period is optional (no date filter unless set)."""

    def __init__(
        self,
        period: Optional[str] = Query(
            None,
            description=(
                "Optional preset: this_month, last_month, this_year, last_year, "
                "all_time, date, custom"
            ),
        ),
        date: Optional[datetime] = Query(None, description="Single calendar day"),
        start_date: Optional[datetime] = Query(None, description="Custom range start"),
        end_date: Optional[datetime] = Query(None, description="Custom range end"),
    ):
        self.resolved: Optional[ResolvedTimePeriod] = None
        if not period and not date and not start_date and not end_date:
            return
        try:
            self.resolved = resolve_date_filter(
                period=period,
                date=date,
                start_date=start_date,
                end_date=end_date,
                default_period=ALL_TIME,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def as_meta(self) -> Optional[dict]:
        return self.resolved.as_dict() if self.resolved else None


# ==================== Filter Dependencies ====================

def _optional_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class ExpenseFilters:
    """Filter parameters for expense list endpoint"""

    def __init__(
        self,
        status: Optional[str] = Query(
            None, description="Filter by status (draft, submitted, approved, rejected)"
        ),
        statuses: Optional[str] = Query(
            None,
            description="Comma-separated statuses e.g. draft,submitted (overrides status)",
        ),
        main_category: Optional[str] = Query(None, description="Filter by main category"),
        sub_category: Optional[str] = Query(None, description="Filter by sub category"),
        transaction_type: Optional[str] = Query(
            None,
            description="expense, out, income, in — defaults to expense in list endpoint",
        ),
        period: Optional[str] = Query(
            None,
            description=(
                "Preset: this_month, last_month, this_year, last_year, all_time, "
                "date, custom"
            ),
        ),
        date: Optional[datetime] = Query(
            None, description="Single day filter (custom date)"
        ),
        start_date: Optional[datetime] = Query(
            None, description="Custom range start (pair with end_date)"
        ),
        end_date: Optional[datetime] = Query(
            None, description="Custom range end (defaults to today if only start_date)"
        ),
        min_amount: Optional[float] = Query(None, ge=0, description="Minimum amount"),
        max_amount: Optional[float] = Query(None, ge=0, description="Maximum amount"),
        search: Optional[str] = Query(None, description="Search in expense name or vendor"),
        upload_method: Optional[str] = Query(None, description="manual or ocr"),
        hashtag: Optional[str] = Query(None, description="Filter by hashtag tag (without #)"),
    ):
        status_text = _optional_str(status)
        if status_text:
            try:
                self.status = ExpenseStatus(status_text)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status_text}") from exc
        else:
            self.status = None

        statuses_text = _optional_str(statuses)
        if statuses_text:
            try:
                self.statuses = [
                    ExpenseStatus(s.strip())
                    for s in statuses_text.split(",")
                    if s.strip()
                ]
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid statuses: {statuses_text}",
                ) from exc
        else:
            self.statuses = None

        main_cat_text = _optional_str(main_category)
        if main_cat_text:
            try:
                self.main_category = MainCategory(main_cat_text)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid main_category: {main_cat_text}",
                ) from exc
        else:
            self.main_category = None

        self.sub_category = _optional_str(sub_category)
        try:
            self.transaction_type = coerce_transaction_type(transaction_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            resolved = resolve_date_filter(
                period=_optional_str(period),
                date=date,
                start_date=start_date,
                end_date=end_date,
                default_period=None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if resolved:
            self.period = resolved.period
            self.is_all_time = resolved.is_all_time
            self.start_date = resolved.start_date
            self.end_date = resolved.end_date if not resolved.is_all_time else None
            self.filter_type = resolved.filter_type
        else:
            self.period = None
            self.is_all_time = False
            self.filter_type = None
            self.start_date = None
            self.end_date = None
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.search = _optional_str(search)
        self.upload_method = _optional_str(upload_method)
        self.hashtag = _optional_str(hashtag)
    
    def apply_to_query(self, query, model):
        """Apply filters to SQLAlchemy query"""
        if self.status:
            query = query.filter(model.status == self.status)
        
        if self.main_category:
            query = query.filter(model.main_category == self.main_category)
        
        if self.sub_category:
            query = query.filter(model.sub_category == self.sub_category)
        
        if self.transaction_type:
            query = query.filter(model.transaction_type == self.transaction_type)
        
        if getattr(self, "is_all_time", False):
            return query

        if self.start_date:
            query = query.filter(model.bill_date >= self.start_date)

        if self.end_date:
            query = query.filter(model.bill_date <= self.end_date)
        
        if self.min_amount:
            query = query.filter(model.bill_amount >= self.min_amount)
        
        if self.max_amount:
            query = query.filter(model.bill_amount <= self.max_amount)
        
        if self.search:
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    model.bill_name.ilike(f"%{self.search}%"),
                    model.vendor_name.ilike(f"%{self.search}%"),
                    model.description.ilike(f"%{self.search}%"),
                    model.bill_number.ilike(f"%{self.search}%")
                )
            )
        
        if self.upload_method:
            query = query.filter(model.upload_method == self.upload_method)
        
        return query

# ==================== Date Range Dependencies ====================

class DateRangeParams:
    """Date range parameters for reports and analytics"""
    
    def __init__(
        self,
        start_date: Optional[datetime] = Query(None, description="Start date"),
        end_date: Optional[datetime] = Query(None, description="End date"),
        period: Optional[str] = Query("month", regex="^(day|week|month|year|all)$", description="Predefined period")
    ):
        self.end_date = end_date or datetime.utcnow()
        
        if start_date:
            self.start_date = start_date
        else:
            # Calculate based on period
            if period == "day":
                self.start_date = self.end_date - timedelta(days=1)
            elif period == "week":
                self.start_date = self.end_date - timedelta(weeks=1)
            elif period == "month":
                self.start_date = self.end_date - timedelta(days=30)
            elif period == "year":
                self.start_date = self.end_date - timedelta(days=365)
            else:  # all
                self.start_date = datetime(2000, 1, 1)
    
    def get_dates(self):
        """Return tuple of (start_date, end_date)"""
        return self.start_date, self.end_date

# ==================== Rate Limiting Dependencies ====================

# Simple in-memory rate limiter (for production, use Redis)
class RateLimiter:
    """Simple rate limiter using in-memory store"""
    
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests = {}  # {ip: [(timestamp, count)]}
    
    async def __call__(self, request: Request):
        client_ip = request.client.host
        current_time = datetime.utcnow()
        minute_ago = current_time - timedelta(minutes=1)
        
        # Clean old requests
        if client_ip in self.requests:
            self.requests[client_ip] = [
                (ts, count) for ts, count in self.requests[client_ip]
                if ts > minute_ago
            ]
        else:
            self.requests[client_ip] = []
        
        # Count requests in last minute
        total_requests = sum(count for _, count in self.requests[client_ip])
        
        if total_requests >= self.requests_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {self.requests_per_minute} requests per minute."
            )
        
        # Add current request
        self.requests[client_ip].append((current_time, 1))

# Rate limiter instances
rate_limiter_60 = RateLimiter(60)  # 60 requests per minute
rate_limiter_120 = RateLimiter(120)  # 120 requests per minute
rate_limiter_300 = RateLimiter(300)  # 300 requests per minute

# ==================== Common Response Models ====================

from pydantic import BaseModel
from typing import Generic, TypeVar

T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response model"""
    items: List[T]
    total: int
    skip: int
    limit: int
    has_more: bool

class MessageResponse(BaseModel):
    """Simple message response"""
    message: str
    status: str = "success"
    timestamp: datetime = datetime.utcnow()

class ErrorResponse(BaseModel):
    """Error response model"""
    error: str
    detail: Optional[str] = None
    status_code: int
    timestamp: datetime = datetime.utcnow()

# ==================== Permission Dependencies ====================

def require_permission(permission: str):
    """Dependency factory for permission checking"""
    async def permission_dependency(
        current_user: User = Depends(get_default_user)
    ) -> User:
        # Implement permission logic based on your role system
        # For now, only check admin status
        if permission == "admin" and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required"
            )
        return current_user
    return permission_dependency

# Convenience permissions
require_admin = require_permission("admin")

# ==================== Database Session Dependency ====================

# Re-export get_db from database module
from app.database import get_db

# ==================== Common Utilities ====================

class RequestContext:
    """Request context with user and other metadata"""
    
    def __init__(self, user: Optional[User] = None, request_id: Optional[str] = None):
        self.user = user
        self.request_id = request_id or self._generate_request_id()
        self.start_time = datetime.utcnow()
    
    @staticmethod
    def _generate_request_id() -> str:
        """Generate unique request ID"""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds"""
        return (datetime.utcnow() - self.start_time).total_seconds()

async def get_request_context(
    request: Request,
    current_user: User = Depends(get_default_user),
) -> RequestContext:
    """Get request context with user and metadata"""
    request_id = request.headers.get("X-Request-ID")
    return RequestContext(user=current_user, request_id=request_id)

# ==================== Validation Dependencies ====================

def validate_expense_ownership(expense_id: int):
    """Validate that the current user owns the expense"""
    async def dependency(
        expense_id: int = expense_id,
        current_user: User = Depends(get_default_user),
        db: Session = Depends(get_db)
    ):
        from app.models import Expense

        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if not expense:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Expense not found"
            )
        
        if expense.user_id != current_user.id and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access this expense"
            )
        
        return expense
    
    return dependency

# ==================== File Upload Dependencies ====================

class FileUploadLimits:
    """File upload limits and validation"""
    
    def __init__(
        self,
        max_size_mb: int = 10,
        allowed_extensions: List[str] = None
    ):
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.allowed_extensions = allowed_extensions or ['jpg', 'jpeg', 'png', 'pdf', 'webp', 'avi']
    
    async def __call__(self, file: UploadFile):
        from fastapi import UploadFile
        
        # Validate extension
        file_extension = file.filename.split('.')[-1].lower()
        if file_extension not in self.allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type '{file_extension}' not allowed. Allowed: {', '.join(self.allowed_extensions)}"
            )
        
        # Size check will be done when reading file
        return file

# File upload limit instances
bill_file_limits = FileUploadLimits(max_size_mb=10)
ocr_file_limits = FileUploadLimits(max_size_mb=20, allowed_extensions=['jpg', 'jpeg', 'png', 'pdf'])

# Export commonly used dependencies
__all__ = [
    "get_default_user",

    # Pagination
    "PaginationParams",
    "PaginatedResponse",
    
    # Filters
    "ExpenseFilters",
    "TimePeriodFilter",
    "OptionalTimePeriodFilter",
    "DateRangeParams",
    
    # Rate Limiting
    "rate_limiter_60",
    "rate_limiter_120",
    "rate_limiter_300",
    
    # Database
    "get_db",
    
    # Utilities
    "get_request_context",
    "RequestContext",
    "validate_expense_ownership",
    "require_admin",
    
    # Models
    "MessageResponse",
    "ErrorResponse",
    
    # File Upload
    "bill_file_limits",
    "ocr_file_limits",
]