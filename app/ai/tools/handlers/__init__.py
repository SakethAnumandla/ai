"""Wire Phase 2/5/6 handlers with per-request database session."""
from sqlalchemy.orm import Session

from app.ai.tools.registry import ToolRegistry

from app.ai.tools.handlers import (
    expense_handlers,
    approval_handlers,
    analytics_handlers,
    manager_handlers,
    finance_handlers,
    executive_handlers,
)


def wire_handlers(registry: ToolRegistry, db: Session) -> None:
    """Bind ERP service handlers; db injected per request (never global)."""

    def bind(fn):
        async def wrapped(*, user, ctx, **kwargs):
            return await fn(db=db, user=user, ctx=ctx, **kwargs)
        return wrapped

    mapping = {
        "expense.create.v1": expense_handlers.handle_expense_create_v1,
        "expense.submit.v1": expense_handlers.handle_expense_submit_v1,
        "expense.search.v1": expense_handlers.handle_expense_search_v1,
        "expense.update.v1": expense_handlers.handle_expense_update_v1,
        "expense.delete.v1": expense_handlers.handle_expense_delete_v1,
        "expense.get.v1": expense_handlers.handle_expense_get_v1,
        "expense.approval.pending.v1": expense_handlers.handle_expense_approval_pending_v1,
        "expense.approval.action.v1": expense_handlers.handle_expense_approval_action_v1,
        "approval.pending.v1": approval_handlers.handle_approval_pending_v1,
        "approval.submit.v1": approval_handlers.handle_approval_submit_v1,
        "approval.flagged.v1": manager_handlers.handle_approval_flagged_v1,
        "approval.explain.v1": manager_handlers.handle_approval_explain_v1,
        "approval.risk_explain.v1": manager_handlers.handle_approval_risk_explain_v1,
        "approval.simulate.v1": manager_handlers.handle_approval_simulate_v1,
        "approval.bulk_export.v1": manager_handlers.handle_approval_bulk_export_v1,
        "approval.bulk_approve.v1": manager_handlers.handle_approval_bulk_approve_v1,
        "approval.bulk_reject.v1": manager_handlers.handle_approval_bulk_reject_v1,
        "reimbursement.submit.v1": approval_handlers.handle_reimbursement_submit_v1,
        "analytics.monthly_spend.v1": finance_handlers.handle_analytics_monthly_spend_v1,
        "analytics.department_trends.v1": finance_handlers.handle_analytics_department_trends_v1,
        "analytics.category_breakdown.v1": finance_handlers.handle_analytics_category_breakdown_v1,
        "analytics.vendor_breakdown.v1": finance_handlers.handle_analytics_vendor_breakdown_v1,
        "analytics.policy_violations.v1": finance_handlers.handle_analytics_policy_violations_v1,
        "analytics.approval_delays.v1": finance_handlers.handle_analytics_approval_delays_v1,
        "analytics.reimbursements.v1": finance_handlers.handle_analytics_reimbursements_v1,
        "analytics.forecast_seed.v1": finance_handlers.handle_analytics_forecast_seed_v1,
        "analytics.team_spend.v1": manager_handlers.handle_analytics_team_spend_v1,
        "analytics.department_risk.v1": manager_handlers.handle_analytics_department_risk_v1,
        "analytics.vendor_patterns.v1": manager_handlers.handle_analytics_vendor_patterns_v1,
        "escalation.create.v1": manager_handlers.handle_escalation_create_v1,
        "escalation.list.v1": manager_handlers.handle_escalation_list_v1,
        "executive.financial_health.v1": executive_handlers.handle_executive_financial_health_v1,
        "executive.operational_risk.v1": executive_handlers.handle_executive_operational_risk_v1,
        "executive.kpi_summary.v1": executive_handlers.handle_executive_kpi_summary_v1,
        "executive.vendor_growth.v1": executive_handlers.handle_executive_vendor_growth_v1,
        "executive.department_efficiency.v1": executive_handlers.handle_executive_department_efficiency_v1,
        "executive.forecast_summary.v1": executive_handlers.handle_executive_forecast_summary_v1,
        "executive.executive_pack.v1": executive_handlers.handle_executive_executive_pack_v1,
        "executive.strategic_recommendations.v1": executive_handlers.handle_executive_strategic_recommendations_v1,
    }
    for name, handler in mapping.items():
        tool = registry.get(name)
        if tool is not None:
            tool.handler = bind(handler)
