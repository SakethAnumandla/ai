"""Phase 5 manager copilot tool handlers."""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.ai.schemas.common import SessionContext, TenantUserContext
from app.ai.schemas.tool_result import ToolResult
from app.ai.security import resolve_tenant_id
from app.manager.approval_insight import ApprovalInsightService
from app.manager.bulk_planner import BulkApprovalPlanner
from app.manager.analytics import ManagerAnalyticsService
from app.manager.escalation import EscalationService
from app.manager.memory import ManagerMemoryService
from app.manager.policy_explanation import PolicyExplanationService
from app.manager.risk_engine import ApprovalRiskEngine
from app.manager.risk_explainability import RiskExplainabilityService
from app.manager.simulation import ApprovalSimulationService
from app.manager.schemas import BulkApprovalFilters
from app.models import Claim, ClaimApproval, User, UserRole


def _manager_roles(user: User) -> bool:
    return user.role in (
        UserRole.MANAGER,
        UserRole.DEPARTMENT_HEAD,
        UserRole.FINANCE_ADMIN,
        UserRole.SUPER_ADMIN,
    )


def _deny_if_not_manager(user: User) -> Optional[ToolResult]:
    if not _manager_roles(user):
        return ToolResult.fail("This tool requires a manager or finance role.", error="role_denied")
    return None


async def handle_approval_pending_v1(
    *, db: Session, user: User, ctx: SessionContext, **_
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied

    insight = ApprovalInsightService(db)
    summary = insight.summarize_queue(user.id)
    candidates = insight.list_prioritized_pending(user.id)
    urgent = [c for c in candidates if getattr(c, "priority_score", 0) >= 0.4][:5]
    urgent_hint = ""
    if urgent:
        top = urgent[0]
        urgent_hint = f" Most urgent: {top.bill_name} (priority {top.priority_rank}, waiting {top.hours_waiting}h)."

    mem = ManagerMemoryService(db)
    tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    behavior = mem.get_behavior_summary(tu)

    return ToolResult.ok(
        message=summary.summary_text + urgent_hint,
        data={
            "queue_summary": summary.model_dump(mode="json"),
            "approvals": [c.model_dump(mode="json") for c in candidates[:25]],
            "manager_memory_hint": behavior.get("summary"),
            "sorted_by": "priority",
        },
    )


async def handle_approval_flagged_v1(
    *, db: Session, user: User, ctx: SessionContext, **_
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied

    flagged = ApprovalInsightService(db).list_flagged(user.id)
    if not flagged:
        return ToolResult.ok(message="No flagged claims in your pending queue.", data={"flagged": []})
    return ToolResult.ok(
        message=f"You have {len(flagged)} flagged claim(s) requiring review.",
        data={"flagged": [c.model_dump(mode="json") for c in flagged]},
    )


async def handle_approval_explain_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    claim_id: Optional[int] = None,
    approval_id: Optional[int] = None,
    include_risk_breakdown: bool = True,
    **_,
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied

    svc = PolicyExplanationService(db)
    try:
        if approval_id:
            expl = svc.explain_by_approval(approval_id, user.id)
            cid = expl.claim_id
        elif claim_id:
            expl = svc.explain_claim(claim_id, approver_id=user.id)
            cid = claim_id
        else:
            return ToolResult.fail("Provide claim_id or approval_id.", error="missing_id")
    except ValueError as exc:
        return ToolResult.fail(str(exc), error="not_found")

    data = expl.model_dump(mode="json")
    if include_risk_breakdown:
        claim = db.query(Claim).filter(Claim.id == cid).first()
        if claim:
            risk = ApprovalRiskEngine(db).score_claim(claim, policy=claim.policy)
            data["risk_breakdown"] = RiskExplainabilityService().explain_claim(
                risk, claim, claim.policy
            ).model_dump(mode="json")

    text = " ".join(expl.reasons)
    if data.get("risk_breakdown", {}).get("summary"):
        text += " " + data["risk_breakdown"]["summary"]
    return ToolResult.ok(message=text, data=data)


async def handle_approval_risk_explain_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    claim_id: Optional[int] = None,
    approval_id: Optional[int] = None,
    **_,
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied

    if approval_id:
        row = (
            db.query(ClaimApproval)
            .filter(ClaimApproval.id == approval_id, ClaimApproval.approver_id == user.id)
            .first()
        )
        if not row:
            return ToolResult.fail("Approval not found", error="not_found")
        claim_id = row.claim_id

    if not claim_id:
        return ToolResult.fail("Provide claim_id or approval_id.", error="missing_id")

    claim = db.query(Claim).filter(Claim.id == claim_id).first()
    if not claim:
        return ToolResult.fail("Claim not found", error="not_found")

    risk = ApprovalRiskEngine(db).score_claim(claim, policy=claim.policy)
    breakdown = RiskExplainabilityService().explain_claim(risk, claim, claim.policy)
    return ToolResult.ok(
        message=breakdown.summary,
        data=breakdown.model_dump(mode="json"),
    )


async def handle_approval_simulate_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    filters: Optional[Dict[str, Any]] = None,
    approval_ids: Optional[List[int]] = None,
    **_,
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied

    f = BulkApprovalFilters.model_validate(filters) if filters else None
    result = ApprovalSimulationService(db).simulate_bulk_approve(
        user, filters=f, approval_ids=approval_ids
    )
    return ToolResult.ok(message=result.summary_text, data=result.model_dump(mode="json"))


async def handle_approval_bulk_export_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    filters: Optional[Dict[str, Any]] = None,
    export_format: str = "csv",
    include_simulation: bool = True,
    **_,
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied

    f = BulkApprovalFilters.model_validate(filters or {})
    preview = BulkApprovalPlanner(db).preview(
        user,
        f,
        include_export=True,
        export_format=export_format,
        include_simulation=include_simulation,
    )
    if preview.count == 0:
        return ToolResult.ok(message="No claims match filters.", data={"preview": preview.model_dump(mode="json")})

    export = preview.export or {}
    return ToolResult.ok(
        message=f"Exported {preview.count} claim(s) as {export_format}. {preview.summary_text}",
        data={
            "preview": preview.model_dump(mode="json"),
            "export": export,
            "download_hint": export.get("download_hint"),
        },
    )


async def handle_approval_bulk_approve_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    preview_only: bool = True,
    filters: Optional[Dict[str, Any]] = None,
    approval_ids: Optional[List[int]] = None,
    idempotency_key: Optional[str] = None,
    comment: Optional[str] = None,
    include_export: bool = False,
    export_format: str = "csv",
    include_simulation: bool = True,
    **_,
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied

    planner = BulkApprovalPlanner(db)
    f = BulkApprovalFilters.model_validate(filters or {})

    if preview_only or not approval_ids:
        preview = planner.preview(
            user,
            f,
            include_export=include_export,
            export_format=export_format,
            include_simulation=include_simulation,
        )
        if preview.count == 0:
            return ToolResult.ok(
                message="No claims match your filters.",
                data={"preview": preview.model_dump(mode="json")},
            )
        return ToolResult.ok(
            message=preview.summary_text,
            data={
                "preview": preview.model_dump(mode="json"),
                "requires_confirmation": True,
                "next_step": "Call again with preview_only=false, approval_ids, and idempotency_key after user confirms.",
            },
        )

    if not idempotency_key:
        return ToolResult.fail("idempotency_key required for bulk execution.", error="missing_idempotency")

    result = planner.execute_approve(user, approval_ids, comment=comment)
    mem = ManagerMemoryService(db)
    tu = TenantUserContext(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    for aid in result.get("approved", []):
        mem.record_decision(tu, decision="approved", claim_id=aid, amount=0)

    return ToolResult.ok(
        message=f"Bulk approved {len(result['approved'])} claim(s); skipped {len(result['skipped'])}.",
        data=result,
    )


async def handle_approval_bulk_reject_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    preview_only: bool = True,
    filters: Optional[Dict[str, Any]] = None,
    approval_ids: Optional[List[int]] = None,
    idempotency_key: Optional[str] = None,
    comment: Optional[str] = None,
    **_,
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied

    planner = BulkApprovalPlanner(db)
    f = BulkApprovalFilters.model_validate(filters or {})

    if preview_only or not approval_ids:
        preview = planner.preview(user, f)
        return ToolResult.ok(
            message=f"Preview: {preview.count} claim(s) would be rejected totaling ₹{preview.total_amount:,.2f}.",
            data={"preview": preview.model_dump(mode="json"), "requires_confirmation": True},
        )

    if not idempotency_key:
        return ToolResult.fail("idempotency_key required.", error="missing_idempotency")

    result = planner.execute_reject(user, approval_ids, comment=comment)
    return ToolResult.ok(
        message=f"Bulk rejected {len(result['rejected'])} claim(s).",
        data=result,
    )


async def handle_analytics_team_spend_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    months: int = 1,
    main_category: Optional[str] = None,
    **_,
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied
    data = ManagerAnalyticsService(db).team_spend(user, months=months, main_category=main_category)
    return ToolResult.ok(
        message=f"Team spend: ₹{data['total_spend']:,.2f} over {months} month(s).",
        data=data,
    )


async def handle_analytics_department_risk_v1(
    *, db: Session, user: User, ctx: SessionContext, **_
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied
    data = ManagerAnalyticsService(db).department_risk_summary(user)
    return ToolResult.ok(message="Department risk summary for pending claims.", data=data)


async def handle_analytics_approval_delays_v1(
    *, db: Session, user: User, ctx: SessionContext, **_
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied
    data = ManagerAnalyticsService(db).approval_delays(user.id)
    return ToolResult.ok(
        message=f"Average wait: {data['average_hours_waiting']} hours across {data['pending_count']} pending.",
        data=data,
    )


async def handle_analytics_vendor_patterns_v1(
    *, db: Session, user: User, ctx: SessionContext, limit: int = 10, **_
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied
    data = ManagerAnalyticsService(db).vendor_patterns(user, limit=limit)
    top = data.get("vendors", [])[:3]
    names = ", ".join(v["vendor"] for v in top) if top else "none"
    return ToolResult.ok(message=f"Top vendors: {names}.", data=data)


async def handle_escalation_create_v1(
    *,
    db: Session,
    user: User,
    ctx: SessionContext,
    claim_id: int,
    reason: str,
    approval_id: Optional[int] = None,
    target_role: str = "finance_admin",
    idempotency_key: Optional[str] = None,
    **_,
) -> ToolResult:
    denied = _deny_if_not_manager(user)
    if denied:
        return denied

    svc = EscalationService(db)
    try:
        row = svc.create(
            tenant_id=resolve_tenant_id(user),
            escalated_by=user.id,
            claim_id=claim_id,
            reason=reason,
            target_role=target_role,
            approval_id=approval_id,
        )
    except ValueError as exc:
        return ToolResult.fail(str(exc), error="escalation_failed")
    return ToolResult.ok(
        message=f"Escalation #{row.id} created for claim #{claim_id}.",
        data=row.model_dump(mode="json"),
    )


async def handle_escalation_list_v1(
    *, db: Session, user: User, ctx: SessionContext, target_role: Optional[str] = None, **_
) -> ToolResult:
    if user.role not in (UserRole.FINANCE_ADMIN, UserRole.SUPER_ADMIN, UserRole.MANAGER):
        return ToolResult.fail("Not authorized.", error="role_denied")
    rows = EscalationService(db).list_open(
        tenant_id=resolve_tenant_id(user),
        target_role=target_role,
    )
    return ToolResult.ok(
        message=f"{len(rows)} open escalation(s).",
        data={"escalations": [r.model_dump(mode="json") for r in rows]},
    )
