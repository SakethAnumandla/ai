"""Bulk approval planner — schema-bound filters, preview, batched execution."""
import uuid
from typing import List, Optional

from sqlalchemy.orm import Session

from app.manager.approval_insight import ApprovalInsightService
from app.manager.dry_run_export import BulkDryRunExporter
from app.manager.schemas import ApprovalCandidate, BulkApprovalFilters, BulkApprovalPreview
from app.models import ApprovalStatus, User
from app.services.claim_service import ClaimService


class BulkApprovalPlanner:
    def __init__(self, db: Session):
        self._db = db
        self._insight = ApprovalInsightService(db)
        self._claims = ClaimService(db)

    def preview(
        self,
        approver: User,
        filters: BulkApprovalFilters,
        *,
        include_export: bool = False,
        export_format: str = "csv",
        include_simulation: bool = False,
    ) -> BulkApprovalPreview:
        candidates = self._apply_filters(approver.id, filters)
        total = sum(c.bill_amount for c in candidates)
        flagged = sum(1 for c in candidates if c.risk.risk_score >= 0.35 or c.policy_flags)
        high_risk = sum(1 for c in candidates if c.risk.risk_score >= 0.5)

        lines = [
            f"I found {len(candidates)} claim(s) totaling ₹{total:,.2f}.",
        ]
        if high_risk:
            lines.append(f"{high_risk} have medium/high risk flags.")
        if flagged:
            lines.append(f"{flagged} are flagged for policy review.")
        lines.append("Review the preview and confirm before I execute bulk approval.")

        preview = BulkApprovalPreview(
            candidates=candidates,
            total_amount=round(total, 2),
            count=len(candidates),
            flagged_count=flagged,
            high_risk_count=high_risk,
            summary_text=" ".join(lines),
            approval_ids=[c.approval_id for c in candidates],
        )
        if include_simulation:
            from app.manager.simulation import ApprovalSimulationService

            sim = ApprovalSimulationService(self._db).simulate_bulk_approve(
                approver, filters=filters
            )
            preview.simulation = sim.model_dump(mode="json")
            if sim.would_exceed_budget:
                preview.summary_text += " " + sim.summary_text
        if include_export and candidates:
            fmt = export_format if export_format in ("csv", "html", "pdf") else "csv"
            preview.export = BulkDryRunExporter().export_preview(
                user_id=approver.id,
                preview=preview,
                action="approve",
                export_format=fmt,  # type: ignore[arg-type]
            )
            preview.summary_text += " Export ready for CSV/HTML review."
        return preview

    def execute_approve(
        self,
        approver: User,
        approval_ids: List[int],
        *,
        comment: Optional[str] = None,
        skip_high_risk: bool = True,
        max_risk_score: float = 0.85,
    ) -> dict:
        """Execute batched approvals — caller must have human confirmation."""
        approved = []
        skipped = []
        errors = []

        for aid in approval_ids:
            candidates = self._insight.list_actionable_pending(approver.id)
            match = next((c for c in candidates if c.approval_id == aid), None)
            if not match:
                errors.append({"approval_id": aid, "error": "not actionable"})
                continue
            if skip_high_risk and match.risk.risk_score >= max_risk_score:
                skipped.append({
                    "approval_id": aid,
                    "reason": "risk_too_high",
                    "risk_score": match.risk.risk_score,
                })
                continue
            try:
                self._claims.process_approval(
                    aid,
                    approver.id,
                    ApprovalStatus.APPROVED,
                    comments=comment or "Bulk approval via manager copilot",
                    approved_amount=match.bill_amount,
                )
                approved.append(aid)
            except ValueError as exc:
                errors.append({"approval_id": aid, "error": str(exc)})

        self._db.commit()
        return {
            "approved": approved,
            "skipped": skipped,
            "errors": errors,
            "batch_id": str(uuid.uuid4()),
        }

    def execute_reject(
        self,
        approver: User,
        approval_ids: List[int],
        *,
        comment: Optional[str] = None,
    ) -> dict:
        rejected = []
        errors = []
        for aid in approval_ids:
            try:
                self._claims.process_approval(
                    aid,
                    approver.id,
                    ApprovalStatus.REJECTED,
                    comments=comment or "Bulk rejection via manager copilot",
                )
                rejected.append(aid)
            except ValueError as exc:
                errors.append({"approval_id": aid, "error": str(exc)})
        self._db.commit()
        return {"rejected": rejected, "errors": errors, "batch_id": str(uuid.uuid4())}

    def _apply_filters(
        self, approver_id: int, filters: BulkApprovalFilters
    ) -> List[ApprovalCandidate]:
        all_pending = self._insight.list_actionable_pending(approver_id)
        out: List[ApprovalCandidate] = []

        for c in all_pending:
            if filters.main_category and (c.main_category or "").lower() != filters.main_category.lower():
                continue
            if filters.max_amount is not None and c.bill_amount > filters.max_amount:
                continue
            if filters.min_amount is not None and c.bill_amount < filters.min_amount:
                continue
            if filters.department and (c.department or "").lower() != filters.department.lower():
                continue
            if filters.max_risk_score is not None and c.risk.risk_score > filters.max_risk_score:
                continue
            if filters.flagged_only and c.risk.risk_score < 0.35 and not c.policy_flags:
                continue
            if filters.vendor_name:
                vn = (c.vendor_name or "").lower()
                if filters.vendor_name.lower() not in vn:
                    continue
            out.append(c)
        return out
