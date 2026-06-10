"""Fine-grained tool permission matrix: role + tool + action + scope."""

import logging

from enum import Enum

from typing import Dict, Optional



from sqlalchemy.orm import Session




from app.models import User, UserRole



logger = logging.getLogger(__name__)





class PermissionAction(str, Enum):

    EXECUTE = "execute"

    PROPOSE = "propose"

    VIEW = "view"





class PermissionScope(str, Enum):

    OWN = "own"

    DEPARTMENT = "department"

    TENANT = "tenant"

    GLOBAL = "global"





_MANAGER_TOOLS = {

    "approval.pending.v1": True,

    "approval.submit.v1": True,

    "approval.flagged.v1": True,

    "approval.explain.v1": True,

    "approval.risk_explain.v1": True,

    "approval.simulate.v1": True,

    "approval.bulk_export.v1": True,

    "approval.bulk_approve.v1": True,

    "approval.bulk_reject.v1": True,

    "analytics.team_spend.v1": True,

    "analytics.department_risk.v1": True,

    "analytics.approval_delays.v1": True,

    "analytics.vendor_patterns.v1": True,

    "escalation.create.v1": True,

    "escalation.list.v1": True,

    "expense.approval.pending.v1": True,

    "expense.approval.action.v1": True,

}


_FINANCE_ANALYTICS_TOOLS = {
    "analytics.monthly_spend.v1": True,
    "analytics.department_trends.v1": True,
    "analytics.category_breakdown.v1": True,
    "analytics.vendor_breakdown.v1": True,
    "analytics.policy_violations.v1": True,
    "analytics.approval_delays.v1": True,
    "analytics.reimbursements.v1": True,
    "analytics.forecast_seed.v1": True,
}

_EXECUTIVE_TOOLS = {
    "executive.financial_health.v1": True,
    "executive.operational_risk.v1": True,
    "executive.kpi_summary.v1": True,
    "executive.vendor_growth.v1": True,
    "executive.department_efficiency.v1": True,
    "executive.forecast_summary.v1": True,
    "executive.executive_pack.v1": True,
    "executive.strategic_recommendations.v1": True,
}


_EMPLOYEE_TOOLS = {

    "expense.create.v1": True,

    "expense.submit.v1": True,

    "expense.search.v1": True,

    "expense.update.v1": True,

    "expense.delete.v1": True,

    "expense.get.v1": True,

    "expense.approval.pending.v1": False,

    "expense.approval.action.v1": False,

    "approval.submit.v1": False,

    "approval.pending.v1": False,

    "approval.flagged.v1": False,

    "approval.explain.v1": False,

    "approval.bulk_approve.v1": False,

    "approval.bulk_reject.v1": False,

    "reimbursement.submit.v1": False,

    "analytics.monthly_spend.v1": False,

    "analytics.department_trends.v1": False,

    "analytics.category_breakdown.v1": False,

    "analytics.vendor_breakdown.v1": False,

    "analytics.policy_violations.v1": False,

    "analytics.reimbursements.v1": False,

    "analytics.forecast_seed.v1": False,

    "analytics.team_spend.v1": False,

    "analytics.department_risk.v1": False,

    "analytics.approval_delays.v1": False,

    "analytics.vendor_patterns.v1": False,

    "escalation.create.v1": False,

    "escalation.list.v1": False,

}



_DEFAULT_MATRIX: Dict[str, Dict[str, bool]] = {

    UserRole.EMPLOYEE.value: _EMPLOYEE_TOOLS,

    UserRole.DEPARTMENT_HEAD.value: {

        **_EMPLOYEE_TOOLS,

        **_MANAGER_TOOLS,

        **_FINANCE_ANALYTICS_TOOLS,

        "executive.department_efficiency.v1": True,

    },

    UserRole.MANAGER.value: {

        **_EMPLOYEE_TOOLS,

        **_MANAGER_TOOLS,

        **_FINANCE_ANALYTICS_TOOLS,

        "executive.department_efficiency.v1": True,

    },

    UserRole.FINANCE_ADMIN.value: {

        **_EMPLOYEE_TOOLS,

        **_MANAGER_TOOLS,

        **_FINANCE_ANALYTICS_TOOLS,

        **_EXECUTIVE_TOOLS,

        "expense.delete.v1": False,

        "reimbursement.submit.v1": True,

    },

    UserRole.SUPER_ADMIN.value: {

        **_EMPLOYEE_TOOLS,

        **_MANAGER_TOOLS,

        **_FINANCE_ANALYTICS_TOOLS,

        **_EXECUTIVE_TOOLS,

        "reimbursement.submit.v1": True,

    },

}



_DEPARTMENT_SCOPED_TOOLS = frozenset({

    "analytics.team_spend.v1",

    "analytics.department_risk.v1",

    "analytics.vendor_patterns.v1",

    "analytics.monthly_spend.v1",

    "analytics.vendor_breakdown.v1",

    "analytics.department_trends.v1",

    "analytics.category_breakdown.v1",

    "analytics.policy_violations.v1",

    "analytics.forecast_seed.v1",

    "approval.pending.v1",

    "approval.flagged.v1",

})





class ToolPermissionMatrix:

    def __init__(self, db: Optional[Session] = None):

        self._db = db



    def scope_for_tool(self, tool_name: str) -> PermissionScope:

        if tool_name in _DEPARTMENT_SCOPED_TOOLS:

            return PermissionScope.DEPARTMENT

        return PermissionScope.OWN



    def is_allowed(

        self,

        *,

        user: User,

        tool_name: str,

        tenant_id: int,

        action: PermissionAction = PermissionAction.EXECUTE,

        scope: Optional[PermissionScope] = None,

    ) -> bool:

        role = user.role.value if user.role else UserRole.EMPLOYEE.value

        canonical = tool_name

        scope = scope or self.scope_for_tool(canonical)

        if self._db:
            from app.ai.models.entities import AIToolPermission

            row = (
                self._db.query(AIToolPermission)
                .filter(
                    AIToolPermission.role == role,
                    AIToolPermission.tool_name == canonical,
                    AIToolPermission.action == action.value,
                    AIToolPermission.scope == scope.value,
                    (AIToolPermission.tenant_id == tenant_id) | (AIToolPermission.tenant_id.is_(None)),
                )
                .order_by(AIToolPermission.tenant_id.desc())
                .first()
            )
            if row is not None:
                return bool(row.allowed)

        role_perms = _DEFAULT_MATRIX.get(role, {})

        if canonical in role_perms:

            return role_perms[canonical]

        return False


