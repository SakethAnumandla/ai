"""API-scoped user identity — from request params, not the local users table."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.deps.scope import ExpenseScope
from app.models import Department, User, UserRole


def _role_from_user_type(user_type: Optional[str]) -> UserRole:
    key = (user_type or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in ("super_admin", "admin"):
        return UserRole.SUPER_ADMIN
    if key in ("finance", "finance_admin"):
        return UserRole.FINANCE_ADMIN
    if key in ("hod", "department_head", "head_of_department"):
        return UserRole.DEPARTMENT_HEAD
    if key == "manager":
        return UserRole.MANAGER
    return UserRole.EMPLOYEE


@dataclass
class ApiUser:
    """Lightweight actor passed to services instead of a DB User row."""

    id: int
    company_id: int
    user_type: Optional[str] = None
    currency: Optional[str] = None
    role: UserRole = UserRole.EMPLOYEE
    department: Optional[Department] = Department.ENGINEERING
    is_admin: bool = False
    is_active: bool = True
    email: str = ""
    username: str = ""
    full_name: Optional[str] = None

    @classmethod
    def from_scope(cls, scope: ExpenseScope) -> "ApiUser":
        role = _role_from_user_type(scope.user_type)
        uid = int(scope.user_id)
        return cls(
            id=uid,
            company_id=int(scope.company_id),
            user_type=scope.user_type,
            currency=scope.currency,
            role=role,
            is_admin=role in (UserRole.SUPER_ADMIN, UserRole.FINANCE_ADMIN),
            email=f"user_{uid}@api.local",
            username=f"user_{uid}",
            full_name=f"User {uid}",
        )

    def as_orm_user(self) -> User:
        """Detached User-shaped object for legacy call sites expecting ORM User."""
        return User(
            id=self.id,
            email=self.email or f"user_{self.id}@api.local",
            username=self.username or f"user_{self.id}",
            hashed_password="not-used",
            full_name=self.full_name,
            is_active=self.is_active,
            is_admin=self.is_admin,
            role=self.role,
            department=self.department,
        )
