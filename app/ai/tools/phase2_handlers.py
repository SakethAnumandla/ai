"""
Phase 2 tool handlers — delegate to service layer only (never DB from here).

Wire to ExpenseService / ClaimService in integration PRs.
"""
from app.ai.schemas.common import SessionContext
from app.ai.schemas.tool_result import ToolResult
from app.models import User


async def handle_expense_create_v1(
    *, user: User, ctx: SessionContext, bill_name: str, bill_amount: float, **kwargs
) -> ToolResult:
  # Phase 2: ExpenseService.create_expense(...)
    return ToolResult.ok(
        message=f"Draft expense '{bill_name}' for ₹{bill_amount:,.2f} saved.",
        data={"bill_name": bill_name, "bill_amount": bill_amount, **kwargs},
    )


async def handle_expense_submit_v1(
    *, user: User, ctx: SessionContext, expense_id: int, idempotency_key: str, **kwargs
) -> ToolResult:
    return ToolResult.ok(
        message=f"Expense #{expense_id} submitted for approval.",
        data={"expense_id": expense_id, "idempotency_key": idempotency_key},
    )


async def handle_expense_delete_v1(
    *, user: User, ctx: SessionContext, expense_id: int, **kwargs
) -> ToolResult:
    return ToolResult.ok(
        message=f"Draft expense #{expense_id} deleted.",
        data={"expense_id": expense_id},
    )


async def handle_approval_submit_v1(
    *,
    user: User,
    ctx: SessionContext,
    claim_id: int,
    decision: str,
    idempotency_key: str,
    comment: str = "",
    **kwargs,
) -> ToolResult:
    return ToolResult.ok(
        message=f"Claim #{claim_id} {decision}.",
        data={"claim_id": claim_id, "decision": decision, "idempotency_key": idempotency_key},
    )


async def handle_reimbursement_submit_v1(
    *,
    user: User,
    ctx: SessionContext,
    claim_id: int,
    idempotency_key: str,
    amount: float | None = None,
    **kwargs,
) -> ToolResult:
    amt = amount or 0
    return ToolResult.ok(
        message=f"Reimbursement of ₹{amt:,.2f} initiated for claim #{claim_id}.",
        data={"claim_id": claim_id, "amount": amt, "idempotency_key": idempotency_key},
    )


def wire_phase2_handlers(registry) -> None:
    """Attach handlers to registered tools."""
    mapping = {
        "expense.create.v1": handle_expense_create_v1,
        "expense.submit.v1": handle_expense_submit_v1,
        "expense.delete.v1": handle_expense_delete_v1,
        "approval.submit.v1": handle_approval_submit_v1,
        "reimbursement.submit.v1": handle_reimbursement_submit_v1,
    }
    for name, handler in mapping.items():
        tool = registry.get(name)
        if tool is not None:
            tool.handler = handler
