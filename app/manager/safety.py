"""Manager-safe execution — never auto-approve without confirmation."""
from typing import FrozenSet, Optional

_FINANCIAL_MANAGER_TOOLS: FrozenSet[str] = frozenset({
    "approval.submit.v1",
    "approval.bulk_approve.v1",
    "approval.bulk_reject.v1",
    "reimbursement.submit.v1",
    "escalation.create.v1",
})

_BULK_TOOLS: FrozenSet[str] = frozenset({
    "approval.bulk_approve.v1",
    "approval.bulk_reject.v1",
})


class ManagerExecutionSafety:
    @staticmethod
    def validate_tool_allowed(
        tool_name: str,
        *,
        skip_confirmation: bool,
        confirmation_acknowledged: bool,
        preview_only: bool = False,
    ) -> Optional[str]:
        if preview_only:
            return None
        if confirmation_acknowledged:
            return None
        if tool_name in _BULK_TOOLS and skip_confirmation:
            return (
                "Bulk approval/rejection requires explicit confirmation. "
                "Review the preview summary and confirm in the app."
            )
        if tool_name in _FINANCIAL_MANAGER_TOOLS and skip_confirmation:
            return (
                "Manager financial actions cannot run without explicit confirmation. "
                "AI suggests → you confirm → execution."
            )
        return None

    @staticmethod
    def blocks_risk_bypass(tool_name: str, arguments: dict) -> Optional[str]:
        if tool_name == "approval.bulk_approve.v1" and arguments.get("ignore_risk_flags"):
            return "Cannot bypass risk flags on bulk approval."
        return None
