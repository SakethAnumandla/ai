"""Human-in-the-loop confirmation before financial tool execution."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.ai.models.entities import AIConfirmation
from app.ai.sanitization import sanitize_prompt
from app.config import settings

logger = logging.getLogger(__name__)

_FINANCIAL_TOOLS = frozenset({
    "expense.submit.v1",
    "approval.submit.v1",
    "approval.bulk_approve.v1",
    "approval.bulk_reject.v1",
    "reimbursement.submit.v1",
    "escalation.create.v1",
    "expense.delete.v1",
    "expense.update.v1",
    "submit_expense",
})


def requires_human_confirmation(tool_name: str, *, tool_flag: bool = False) -> bool:
    canonical = tool_name
    return tool_flag or canonical in _FINANCIAL_TOOLS or any(
        t in canonical for t in ("submit", "approve", "reject", "delete", "reimburse", "payout")
    )


class ConfirmationService:
    def __init__(self, db: Session):
        self._db = db

    def create_pending(
        self,
        *,
        tenant_id: int,
        user_id: int,
        session_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        summary_message: str,
    ) -> AIConfirmation:
        token = str(uuid.uuid4())
        expires = datetime.now(timezone.utc) + timedelta(seconds=settings.ai_confirmation_ttl_seconds)
        safe_args = sanitize_prompt(arguments)
        if not isinstance(safe_args, dict):
            safe_args = arguments

        row = AIConfirmation(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            confirmation_token=token,
            tool_name=tool_name,
            arguments=safe_args,
            summary_message=summary_message,
            status="pending",
            expires_at=expires,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        logger.info(
            "confirmation.created",
            extra={"tool_name": tool_name, "tenant_id": tenant_id, "user_id": user_id},
        )
        return row

    def get_pending(self, confirmation_token: str, *, tenant_id: int, user_id: int) -> Optional[AIConfirmation]:
        now = datetime.now(timezone.utc)
        return (
            self._db.query(AIConfirmation)
            .filter(
                AIConfirmation.confirmation_token == confirmation_token,
                AIConfirmation.tenant_id == tenant_id,
                AIConfirmation.user_id == user_id,
                AIConfirmation.status == "pending",
                AIConfirmation.expires_at > now,
            )
            .first()
        )

    def get_latest_expired_for_session(
        self, *, tenant_id: int, user_id: int, session_id: str
    ) -> Optional[AIConfirmation]:
        now = datetime.now(timezone.utc)
        return (
            self._db.query(AIConfirmation)
            .filter(
                AIConfirmation.tenant_id == tenant_id,
                AIConfirmation.user_id == user_id,
                AIConfirmation.session_id == session_id,
                AIConfirmation.status == "pending",
                AIConfirmation.expires_at <= now,
            )
            .order_by(AIConfirmation.created_at.desc())
            .first()
        )

    def get_latest_pending_for_session(
        self, *, tenant_id: int, user_id: int, session_id: str
    ) -> Optional[AIConfirmation]:
        now = datetime.now(timezone.utc)
        return (
            self._db.query(AIConfirmation)
            .filter(
                AIConfirmation.tenant_id == tenant_id,
                AIConfirmation.user_id == user_id,
                AIConfirmation.session_id == session_id,
                AIConfirmation.status == "pending",
                AIConfirmation.expires_at > now,
            )
            .order_by(AIConfirmation.created_at.desc())
            .first()
        )

    def mark_confirmed(self, row: AIConfirmation) -> AIConfirmation:
        row.status = "confirmed"
        row.confirmed_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(row)
        return row

    def mark_cancelled(self, confirmation_token: str, *, tenant_id: int, user_id: int) -> bool:
        row = self.get_pending(confirmation_token, tenant_id=tenant_id, user_id=user_id)
        if not row:
            return False
        row.status = "cancelled"
        self._db.commit()
        return True
