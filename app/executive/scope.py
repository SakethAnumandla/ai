"""Executive access scope — company-wide strategic intelligence."""
from app.models import User, UserRole


EXECUTIVE_ROLES = frozenset({
    UserRole.FINANCE_ADMIN,
    UserRole.SUPER_ADMIN,
})

EXECUTIVE_LIMITED_ROLES = frozenset({
    UserRole.MANAGER,
    UserRole.DEPARTMENT_HEAD,
})


def is_full_executive(user: User) -> bool:
    return user.role in EXECUTIVE_ROLES


def can_use_executive_tools(user: User) -> bool:
    return user.role in EXECUTIVE_ROLES or user.role in EXECUTIVE_LIMITED_ROLES


def can_use_tool(user: User, tool_name: str) -> bool:
    if is_full_executive(user):
        return True
    if user.role in EXECUTIVE_LIMITED_ROLES:
        return tool_name == "executive.department_efficiency.v1"
    return False
