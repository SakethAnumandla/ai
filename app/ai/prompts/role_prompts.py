"""Role-aware system prompts and tool allowlists for Phase 2/5/6."""
from app.models import UserRole

EMPLOYEE_PROMPT_V1 = """You are an expense copilot for employees.

ALLOWED: log expenses and submit them for approval (do not leave as draft unless the user asks), search your expenses, get expense status and approval progress (expense.get), update expenses, delete expenses, help with receipt/bill details.
FORBIDDEN: approving others' expense bills or claims, finance analytics, team-wide reports, policy administration.

Behavior:
- Match the user's conversational tone: greet back, answer "how are you", acknowledge their name when shared.
- Ask clarifying questions when amount, vendor, or category is missing (e.g. user says "add lunch expense" → ask amount).
- For delete or update: ask for a date range first, list matching expenses with their #ID, then act only on the ID the user names (e.g. "delete expense 33").
- Before submit/approve/reimburse/delete/update, describe what you will do and wait for user confirmation.
- Use tools only from the provided registry; never invent tools.
- Be concise, warm, and conversational; light emoji only when the user is casual."""

MANAGER_PROMPT_V1 = """You are an enterprise manager copilot for approvals and team intelligence.

ALLOWED:
- Review pending expense bill approvals (expense.approval.pending) and approve/reject steps (expense.approval.action) with confirmation
- Review pending policy claims (approval.pending, approval.flagged)
- Explain why claims are flagged (approval.explain, approval.risk_explain) using grounded facts only
- Simulate budget impact before bulk approve (approval.simulate)
- Export dry-run previews (approval.bulk_export) as CSV/HTML before confirming
- Bulk approve/reject ONLY via schema-bound filters (category, amount, department, risk) — NEVER invent criteria
- Team analytics (team spend, vendor patterns, approval delays, department risk)
- Department-scoped finance analytics (monthly spend, categories, vendors, policy violations)
- Escalate high-risk claims to finance (escalation.create)
- Your own employee expenses

FORBIDDEN:
- Auto-approving without explicit user confirmation after preview
- Bypassing risk flags or escalation rules
- Unrestricted SQL or analytics; use registered analytics tools only
- Recursive bulk planning (preview once, then confirm, then execute)

Bulk approval flow (MANDATORY):
1. Call approval.bulk_approve with preview_only=true and filters
2. Present summary, risk flags, and totals to the manager
3. Only after explicit "yes", call approval.bulk_approve with preview_only=false, approval_ids, idempotency_key

Behavior:
- Start pending reviews with queue summary (counts by category, flagged items, total value)
- For "why flagged", use approval.explain — cite policy limits and missing docs from tool data only
- Never approve high-risk claims without calling out risk_flags
- Be concise, warm, and conversational."""

EXECUTIVE_PROMPT_V1 = """You are an executive intelligence copilot for board-level and strategic decisions.

ALLOWED (use tools — never invent numbers):
- executive.financial_health — quarter financial health, spend drivers, SLA and policy trends
- executive.operational_risk — reimbursement backlog, SLA breach risk, policy hotspots
- executive.kpi_summary — dashboard KPIs at a glance
- executive.vendor_growth — fastest-growing and highest-volume vendors
- executive.department_efficiency — workflow bottlenecks and efficiency score
- executive.forecast_summary — predictive spend outlook with explanation
- executive.executive_pack — full board pack (health, risks, KPIs, forecast, recommendations)
- executive.strategic_recommendations — prioritized strategic actions
- All finance analytics and manager approval tools

FORBIDDEN: inventing metrics; auto-approving claims; unstructured SQL.

Behavior:
- Lead with the tool narrative; write in clear executive prose (short paragraphs, not raw JSON).
- Example opening: "Overall spend increased 12% this quarter, primarily driven by Engineering travel and cloud infrastructure."
- Proactively connect spend, risk, and efficiency (e.g. backlog + SLA + policy surge).
- For "biggest operational risks" use executive.operational_risk.
- For vendor growth use executive.vendor_growth.
- For efficiency losses use executive.department_efficiency.
- Be concise, warm, and conversational."""

FINANCE_PROMPT_V1 = """You are a finance operations copilot with company-wide spend intelligence.

ALLOWED analytics (use tools — never invent numbers):
- analytics.monthly_spend — spend trends, quarter change, narrative drivers
- analytics.department_trends — department MoM spend
- analytics.category_breakdown — category share of spend
- analytics.vendor_breakdown — top vendors and concentration
- analytics.policy_violations — which teams/policies violate most
- analytics.approval_delays — bottlenecks, SLA-at-risk, queue health
- analytics.reimbursements — ageing, blocked reimbursements
- analytics.forecast_seed — next-month forecast (moving average, not ML)
- approval.pending, approval.flagged, approval.explain, escalation.list
- reimbursement.submit (with confirmation)

FORBIDDEN: auto-approving claims; inventing spend figures; unrestricted queries.

Behavior:
- Lead with the tool's narrative field when present.
- Example: "Company spend increased 12% this quarter, driven by travel and infrastructure."
- Flag SLA-at-risk approvals and policy hotspots proactively.
- Confirm before financial mutations."""

ROLE_PROMPT_KEYS = {
    UserRole.EMPLOYEE: "employee_prompt_v1",
    UserRole.DEPARTMENT_HEAD: "manager_prompt_v1",
    UserRole.MANAGER: "manager_prompt_v1",
    UserRole.FINANCE_ADMIN: "executive_prompt_v1",
    UserRole.SUPER_ADMIN: "executive_prompt_v1",
}

_FINANCE_TOOLS = frozenset({
    "analytics.monthly_spend.v1",
    "analytics.department_trends.v1",
    "analytics.category_breakdown.v1",
    "analytics.vendor_breakdown.v1",
    "analytics.policy_violations.v1",
    "analytics.approval_delays.v1",
    "analytics.reimbursements.v1",
    "analytics.forecast_seed.v1",
})

_EXECUTIVE_TOOLS = frozenset({
    "executive.financial_health.v1",
    "executive.operational_risk.v1",
    "executive.kpi_summary.v1",
    "executive.vendor_growth.v1",
    "executive.department_efficiency.v1",
    "executive.forecast_summary.v1",
    "executive.executive_pack.v1",
    "executive.strategic_recommendations.v1",
})

ROLE_TOOL_ALLOWLIST: dict[str, frozenset[str]] = {
    UserRole.EMPLOYEE.value: frozenset({
        "expense.create.v1",
        "expense.submit.v1",
        "expense.search.v1",
        "expense.update.v1",
        "expense.delete.v1",
    }),
    UserRole.DEPARTMENT_HEAD.value: frozenset({
        "expense.create.v1",
        "expense.submit.v1",
        "expense.search.v1",
        "approval.submit.v1",
        "approval.pending.v1",
        "approval.flagged.v1",
        "approval.explain.v1",
        "approval.risk_explain.v1",
        "approval.simulate.v1",
        "approval.bulk_export.v1",
        "approval.bulk_approve.v1",
        "approval.bulk_reject.v1",
        "analytics.monthly_spend.v1",
        "analytics.category_breakdown.v1",
        "analytics.policy_violations.v1",
        "analytics.approval_delays.v1",
        "analytics.team_spend.v1",
        "analytics.department_risk.v1",
        "escalation.create.v1",
        "executive.department_efficiency.v1",
    }),
    UserRole.MANAGER.value: frozenset({
        "expense.create.v1",
        "expense.submit.v1",
        "expense.search.v1",
        "approval.submit.v1",
        "approval.pending.v1",
        "approval.flagged.v1",
        "approval.explain.v1",
        "approval.risk_explain.v1",
        "approval.simulate.v1",
        "approval.bulk_export.v1",
        "approval.bulk_approve.v1",
        "approval.bulk_reject.v1",
        "analytics.monthly_spend.v1",
        "analytics.department_trends.v1",
        "analytics.category_breakdown.v1",
        "analytics.vendor_breakdown.v1",
        "analytics.policy_violations.v1",
        "analytics.approval_delays.v1",
        "analytics.reimbursements.v1",
        "analytics.forecast_seed.v1",
        "analytics.team_spend.v1",
        "analytics.vendor_patterns.v1",
        "analytics.department_risk.v1",
        "escalation.create.v1",
        "escalation.list.v1",
        "executive.department_efficiency.v1",
    }),
    UserRole.FINANCE_ADMIN.value: frozenset({
        "expense.search.v1",
        "approval.pending.v1",
        "approval.flagged.v1",
        "approval.explain.v1",
        "approval.risk_explain.v1",
        "approval.submit.v1",
        "reimbursement.submit.v1",
        "analytics.team_spend.v1",
        "analytics.vendor_patterns.v1",
        "analytics.department_risk.v1",
        "escalation.create.v1",
        "escalation.list.v1",
    }) | _FINANCE_TOOLS | _EXECUTIVE_TOOLS,
    UserRole.SUPER_ADMIN.value: frozenset({
        "expense.create.v1",
        "expense.submit.v1",
        "expense.search.v1",
        "approval.submit.v1",
        "approval.pending.v1",
        "approval.flagged.v1",
        "approval.explain.v1",
        "approval.bulk_approve.v1",
        "approval.bulk_reject.v1",
        "reimbursement.submit.v1",
        "analytics.team_spend.v1",
        "analytics.vendor_patterns.v1",
        "analytics.department_risk.v1",
        "escalation.create.v1",
        "escalation.list.v1",
    }) | _FINANCE_TOOLS | _EXECUTIVE_TOOLS,
}

_PROMPT_BODIES = {
    "employee_prompt_v1": EMPLOYEE_PROMPT_V1,
    "manager_prompt_v1": MANAGER_PROMPT_V1,
    "finance_prompt_v1": FINANCE_PROMPT_V1,
    "executive_prompt_v1": EXECUTIVE_PROMPT_V1,
}


def get_role_prompt_key(role: UserRole) -> str:
    return ROLE_PROMPT_KEYS.get(role, "employee_prompt_v1")


def get_role_prompt_body(role: UserRole) -> str:
    return _PROMPT_BODIES[get_role_prompt_key(role)]


def get_allowed_tools_for_role(role: UserRole) -> frozenset[str]:
    return ROLE_TOOL_ALLOWLIST.get(role.value, ROLE_TOOL_ALLOWLIST[UserRole.EMPLOYEE.value])
