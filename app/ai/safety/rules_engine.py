"""Pre-execution safety checks — escalate suspicious financial actions."""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_SUSPICIOUS_VENDORS = frozenset({"unknown", "cash", "test", "na", "n/a", "misc"})


@dataclass
class SafetyVerdict:
    allow: bool = True
    escalate: bool = False
    block: bool = False
    flags: List[str] = field(default_factory=list)
    message: Optional[str] = None


class SafetyRulesEngine:
    """Evaluate tool arguments before confirmation or execution."""

    def evaluate(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        recent_duplicate_amount: Optional[float] = None,
    ) -> SafetyVerdict:
        flags: List[str] = []
        amount = arguments.get("bill_amount") or arguments.get("amount")
        vendor = (arguments.get("vendor_name") or arguments.get("bill_name") or "").strip().lower()

        if amount is not None:
            try:
                amt = float(amount)
                if amt >= settings.ai_high_amount_threshold:
                    flags.append("high_amount")
                if amt <= 0:
                    flags.append("invalid_amount")
            except (TypeError, ValueError):
                flags.append("invalid_amount")

        if vendor in _SUSPICIOUS_VENDORS:
            flags.append("suspicious_vendor")

        if datetime.utcnow().weekday() >= 5 and "submit" in tool_name:
            flags.append("weekend_submission")

        if recent_duplicate_amount is not None and amount is not None:
            try:
                if abs(float(amount) - recent_duplicate_amount) < 0.01:
                    flags.append("possible_duplicate")
            except (TypeError, ValueError):
                pass

        if "invalid_amount" in flags:
            return SafetyVerdict(
                allow=False,
                block=True,
                flags=flags,
                message="Invalid amount — cannot proceed.",
            )

        if flags:
            logger.info("safety.flags", extra={"tool_name": tool_name, "flags": flags})
            return SafetyVerdict(
                allow=True,
                escalate=True,
                flags=flags,
                message="This action has been flagged for review. Please confirm you want to proceed.",
            )

        return SafetyVerdict(allow=True, flags=[])
