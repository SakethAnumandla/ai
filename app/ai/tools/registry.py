"""
Tool registry with versioning — handlers return ToolResult only.
"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from pydantic import BaseModel

from app.ai.schemas.tool_result import ToolResult

ToolHandler = Callable[..., Union[ToolResult, Awaitable[ToolResult]]]

_LEGACY_ALIASES: Dict[str, str] = {
    "create_expense_draft": "expense.create.v1",
    "submit_expense": "expense.submit.v1",
}


def to_openai_tool_name(canonical: str) -> str:
    """OpenAI function names must match ^[a-zA-Z0-9_-]+$ (dots are invalid)."""
    return canonical.replace(".", "-")


def from_openai_tool_name(openai_name: str) -> str:
    """Map OpenAI tool name back to internal dotted canonical name."""
    if "." in openai_name:
        return openai_name
    return openai_name.replace("-", ".")


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters_schema: Dict[str, Any]
    logical_name: str
    version: int = 1
    handler: Optional[ToolHandler] = None
    requires_idempotency: bool = False
    requires_confirmation: bool = False
    aliases: tuple[str, ...] = field(default_factory=tuple)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._logical_latest: Dict[str, str] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools and self._tools[tool.name] is not tool:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            self._tools[alias] = tool
        current = self._logical_latest.get(tool.logical_name)
        if not current or tool.version >= self._tools[current].version:
            self._logical_latest[tool.logical_name] = tool.name

    def resolve_name(self, name: str) -> str:
        if name in self._tools:
            return self._tools[name].name
        decoded = from_openai_tool_name(name)
        if decoded in self._tools:
            return self._tools[decoded].name
        return _LEGACY_ALIASES.get(name, _LEGACY_ALIASES.get(decoded, name))

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(self.resolve_name(name))

    def list_openai_tools(
        self,
        *,
        allowed_names: Optional[frozenset[str]] = None,
    ) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        tools: List[Dict[str, Any]] = []
        for name in self._logical_latest.values():
            if name in seen:
                continue
            if allowed_names and name not in allowed_names:
                continue
            seen.add(name)
            t = self._tools[name]
            tools.append({
                "type": "function",
                "function": {
                    "name": to_openai_tool_name(t.name),
                    "description": f"[v{t.version}] {t.description}",
                    "parameters": t.parameters_schema,
                },
            })
        return tools

    def is_registered(self, name: str) -> bool:
        return self.get(name) is not None


def _idempotency_key_property() -> Dict[str, Any]:
    return {
        "idempotency_key": {
            "type": "string",
            "description": "Client UUID for exactly-once execution",
            "minLength": 8,
            "maxLength": 128,
        }
    }


def default_expense_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(ToolDefinition(
        name="expense.create.v1",
        logical_name="expense.create",
        version=1,
        description="Create an expense. Default flow asks user to confirm submit for approval (not draft-only).",
        aliases=("create_expense_draft",),
        parameters_schema={
            "type": "object",
            "properties": {
                "expense_id": {
                    "type": "integer",
                    "description": "Existing draft expense ID to update (e.g. after OCR). Omit only for a brand-new draft.",
                },
                "review_token": {
                    "type": "string",
                    "description": "OCR human-review token when confirming a scanned receipt draft.",
                },
                "bill_name": {"type": "string"},
                "bill_amount": {"type": "number"},
                "amount": {"type": "number", "description": "Alias for bill_amount"},
                "title": {"type": "string", "description": "Alias for bill_name"},
                "main_category": {"type": "string"},
                "category": {"type": "string", "description": "Alias for main_category"},
                "sub_category": {"type": "string"},
                "subcategory": {"type": "string", "description": "Alias for sub_category"},
                "vendor_name": {"type": "string"},
                "merchant": {"type": "string", "description": "Alias for vendor_name"},
                "vendor": {"type": "string", "description": "Alias for vendor_name"},
                "payment_method": {"type": "string"},
                "description": {
                    "type": "string",
                    "description": "User-originated expense note; do not invent text.",
                },
                "hashtags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keyword tags for the expense",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alias for hashtags",
                },
                "bill_date": {"type": "string"},
                "save_as_draft": {
                    "type": "boolean",
                    "description": "Only true if user explicitly wants a draft. Default: submit for approval.",
                },
            },
            "required": ["bill_name"],
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="expense.submit.v1",
        logical_name="expense.submit",
        version=1,
        description="Submit a draft expense for approval. Requires user confirmation.",
        aliases=("submit_expense",),
        requires_idempotency=True,
        requires_confirmation=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "expense_id": {"type": "integer"},
                **_idempotency_key_property(),
            },
            "required": ["expense_id", "idempotency_key"],
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="expense.search.v1",
        logical_name="expense.search",
        version=1,
        description=(
            "Search expenses by keyword, status, or date range. "
            "Use status=pending for all open bills (draft + submitted awaiting approval)."
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "search_term": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["draft", "submitted", "pending", "approved", "rejected"],
                    "description": "pending = draft and submitted (not yet approved)",
                },
                "start_date": {"type": "string", "description": "Range start, e.g. 2024-10-01 or last week"},
                "end_date": {"type": "string", "description": "Range end"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="expense.update.v1",
        logical_name="expense.update",
        version=1,
        description="Update an existing expense (amount, vendor, category, date). Requires confirmation.",
        aliases=("update_expense",),
        requires_confirmation=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "expense_id": {"type": "integer"},
                "bill_name": {"type": "string"},
                "bill_amount": {"type": "number"},
                "vendor_name": {"type": "string"},
                "main_category": {"type": "string"},
                "sub_category": {"type": "string"},
                "bill_date": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["expense_id"],
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="expense.delete.v1",
        logical_name="expense.delete",
        version=1,
        description="Delete an expense by ID. Requires confirmation.",
        requires_confirmation=True,
        parameters_schema={
            "type": "object",
            "properties": {"expense_id": {"type": "integer"}},
            "required": ["expense_id"],
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="expense.get.v1",
        logical_name="expense.get",
        version=1,
        description=(
            "Get one expense by ID with approval status and workflow progress "
            "(draft → submitted → approvers → approved/rejected)."
        ),
        parameters_schema={
            "type": "object",
            "properties": {"expense_id": {"type": "integer"}},
            "required": ["expense_id"],
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="expense.approval.pending.v1",
        logical_name="expense.approval.pending",
        version=1,
        description="List expense bills awaiting the user's approval (multi-step workflow).",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ))

    registry.register(ToolDefinition(
        name="expense.approval.action.v1",
        logical_name="expense.approval.action",
        version=1,
        description="Approve or reject an expense bill approval step by approval_id. Requires confirmation.",
        requires_idempotency=True,
        requires_confirmation=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "approval_id": {"type": "integer"},
                "action": {"type": "string", "enum": ["approve", "reject"]},
                "comments": {"type": "string"},
                **_idempotency_key_property(),
            },
            "required": ["approval_id", "action", "idempotency_key"],
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="approval.pending.v1",
        logical_name="approval.pending",
        version=1,
        description="List claims pending the user's approval",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ))

    registry.register(ToolDefinition(
        name="approval.submit.v1",
        logical_name="approval.submit",
        version=1,
        description="Approve or reject a claim. Requires confirmation.",
        requires_idempotency=True,
        requires_confirmation=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "approval_id": {"type": "integer"},
                "decision": {"type": "string", "enum": ["approved", "rejected"]},
                "comment": {"type": "string"},
                "approved_amount": {"type": "number"},
                **_idempotency_key_property(),
            },
            "required": ["approval_id", "decision", "idempotency_key"],
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="reimbursement.submit.v1",
        logical_name="reimbursement.submit",
        version=1,
        description="Initiate reimbursement for a claim",
        requires_idempotency=True,
        requires_confirmation=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "integer"},
                "amount": {"type": "number"},
                **_idempotency_key_property(),
            },
            "required": ["claim_id", "idempotency_key"],
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="analytics.monthly_spend.v1",
        logical_name="analytics.monthly_spend",
        version=1,
        description="Spend trends and monthly summary (finance: company-wide)",
        parameters_schema={
            "type": "object",
            "properties": {"months": {"type": "integer"}},
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="analytics.department_trends.v1",
        logical_name="analytics.department_trends",
        version=1,
        description="Department spend trends month-over-month",
        parameters_schema={
            "type": "object",
            "properties": {
                "months": {"type": "integer"},
                "department": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="analytics.category_breakdown.v1",
        logical_name="analytics.category_breakdown",
        version=1,
        description="Spend breakdown by category with share percentages",
        parameters_schema={
            "type": "object",
            "properties": {
                "months": {"type": "integer"},
                "department": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="analytics.vendor_breakdown.v1",
        logical_name="analytics.vendor_breakdown",
        version=1,
        description="Top vendors, concentration, and spend share",
        parameters_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "months": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="analytics.policy_violations.v1",
        logical_name="analytics.policy_violations",
        version=1,
        description="Policy violation trends and department ranking",
        parameters_schema={
            "type": "object",
            "properties": {"months": {"type": "integer"}},
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="analytics.reimbursements.v1",
        logical_name="analytics.reimbursements",
        version=1,
        description="Reimbursement ageing, blocked claims, SLA risks",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ))

    registry.register(ToolDefinition(
        name="analytics.forecast_seed.v1",
        logical_name="analytics.forecast_seed",
        version=1,
        description="Next-month spend forecast (moving average + MoM + seasonal heuristics)",
        parameters_schema={
            "type": "object",
            "properties": {
                "months": {"type": "integer"},
                "department": {"type": "string"},
                "main_category": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ))

    _bulk_filters_schema = {
        "type": "object",
        "properties": {
            "main_category": {"type": "string"},
            "max_amount": {"type": "number"},
            "min_amount": {"type": "number"},
            "department": {"type": "string"},
            "max_risk_score": {"type": "number"},
            "flagged_only": {"type": "boolean"},
            "vendor_name": {"type": "string"},
        },
        "additionalProperties": False,
    }

    registry.register(ToolDefinition(
        name="approval.flagged.v1",
        logical_name="approval.flagged",
        version=1,
        description="List pending claims flagged for policy or risk review",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ))

    registry.register(ToolDefinition(
        name="approval.explain.v1",
        logical_name="approval.explain",
        version=1,
        description="Explain why a claim was flagged (grounded policy + risk reasons)",
        parameters_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "integer"},
                "approval_id": {"type": "integer"},
                "include_risk_breakdown": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="approval.risk_explain.v1",
        logical_name="approval.risk_explain",
        version=1,
        description="Explain why risk_score is high for a claim (score breakdown)",
        parameters_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "integer"},
                "approval_id": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="approval.simulate.v1",
        logical_name="approval.simulate",
        version=1,
        description="Simulate budget/policy impact if claims are approved (no execution)",
        parameters_schema={
            "type": "object",
            "properties": {
                "filters": _bulk_filters_schema,
                "approval_ids": {"type": "array", "items": {"type": "integer"}},
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="approval.bulk_export.v1",
        logical_name="approval.bulk_export",
        version=1,
        description="Export bulk approval dry-run as CSV or printable HTML (PDF via print)",
        parameters_schema={
            "type": "object",
            "properties": {
                "filters": _bulk_filters_schema,
                "export_format": {"type": "string", "enum": ["csv", "html", "pdf"]},
                "include_simulation": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="approval.bulk_approve.v1",
        logical_name="approval.bulk_approve",
        version=1,
        description="Preview or execute bulk approve with schema-bound filters. Always preview first.",
        requires_idempotency=False,
        requires_confirmation=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "preview_only": {"type": "boolean"},
                "filters": _bulk_filters_schema,
                "approval_ids": {"type": "array", "items": {"type": "integer"}},
                "comment": {"type": "string"},
                "include_export": {"type": "boolean"},
                "export_format": {"type": "string", "enum": ["csv", "html", "pdf"]},
                "include_simulation": {"type": "boolean"},
                **_idempotency_key_property(),
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="approval.bulk_reject.v1",
        logical_name="approval.bulk_reject",
        version=1,
        description="Preview or execute bulk reject with schema-bound filters",
        requires_idempotency=False,
        requires_confirmation=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "preview_only": {"type": "boolean"},
                "filters": _bulk_filters_schema,
                "approval_ids": {"type": "array", "items": {"type": "integer"}},
                "comment": {"type": "string"},
                **_idempotency_key_property(),
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="analytics.team_spend.v1",
        logical_name="analytics.team_spend",
        version=1,
        description="Team or department spend summary for managers",
        parameters_schema={
            "type": "object",
            "properties": {
                "months": {"type": "integer"},
                "main_category": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="analytics.department_risk.v1",
        logical_name="analytics.department_risk",
        version=1,
        description="Department risk summary for pending claims",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ))

    registry.register(ToolDefinition(
        name="analytics.approval_delays.v1",
        logical_name="analytics.approval_delays",
        version=1,
        description="Approval delays, bottlenecks, SLA-at-risk (finance: company-wide)",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ))

    registry.register(ToolDefinition(
        name="analytics.vendor_patterns.v1",
        logical_name="analytics.vendor_patterns",
        version=1,
        description="Top vendor spend patterns for your team",
        parameters_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="escalation.create.v1",
        logical_name="escalation.create",
        version=1,
        description="Escalate a claim to finance or audit",
        requires_idempotency=True,
        requires_confirmation=True,
        parameters_schema={
            "type": "object",
            "properties": {
                "claim_id": {"type": "integer"},
                "approval_id": {"type": "integer"},
                "reason": {"type": "string"},
                "target_role": {
                    "type": "string",
                    "enum": ["finance_admin", "super_admin", "audit"],
                },
                **_idempotency_key_property(),
            },
            "required": ["claim_id", "reason", "idempotency_key"],
            "additionalProperties": False,
        },
    ))

    registry.register(ToolDefinition(
        name="escalation.list.v1",
        logical_name="escalation.list",
        version=1,
        description="List open escalations",
        parameters_schema={
            "type": "object",
            "properties": {
                "target_role": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ))

    # Phase 7 — Executive intelligence
    registry.register(ToolDefinition(
        name="executive.financial_health.v1",
        logical_name="executive.financial_health",
        version=1,
        description="Executive financial health summary (quarter spend, drivers, SLA, policy trends)",
        parameters_schema={
            "type": "object",
            "properties": {"quarters": {"type": "integer"}},
            "additionalProperties": False,
        },
    ))
    registry.register(ToolDefinition(
        name="executive.operational_risk.v1",
        logical_name="executive.operational_risk",
        version=1,
        description="Organizational operational risks (reimbursements, SLA, policy, KPI alerts)",
        parameters_schema={
            "type": "object",
            "properties": {"months": {"type": "integer"}},
            "additionalProperties": False,
        },
    ))
    registry.register(ToolDefinition(
        name="executive.kpi_summary.v1",
        logical_name="executive.kpi_summary",
        version=1,
        description="Board-level KPI summary dashboard",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ))
    registry.register(ToolDefinition(
        name="executive.vendor_growth.v1",
        logical_name="executive.vendor_growth",
        version=1,
        description="Fastest-growing vendors and highest-volume vendor",
        parameters_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "additionalProperties": False,
        },
    ))
    registry.register(ToolDefinition(
        name="executive.department_efficiency.v1",
        logical_name="executive.department_efficiency",
        version=1,
        description="Department workflow efficiency (approvals, reimbursements)",
        parameters_schema={
            "type": "object",
            "properties": {"department": {"type": "string"}},
            "additionalProperties": False,
        },
    ))
    registry.register(ToolDefinition(
        name="executive.forecast_summary.v1",
        logical_name="executive.forecast_summary",
        version=1,
        description="Predictive spend outlook with explainability",
        parameters_schema={
            "type": "object",
            "properties": {
                "months": {"type": "integer"},
                "department": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ))
    registry.register(ToolDefinition(
        name="executive.executive_pack.v1",
        logical_name="executive.executive_pack",
        version=1,
        description="Full board-level executive intelligence pack",
        parameters_schema={
            "type": "object",
            "properties": {"quarters": {"type": "integer"}},
            "additionalProperties": False,
        },
    ))
    registry.register(ToolDefinition(
        name="executive.strategic_recommendations.v1",
        logical_name="executive.strategic_recommendations",
        version=1,
        description="Strategic recommendations from spend, risk, and efficiency signals",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
    ))

    return registry
