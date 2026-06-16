"""Contextual reference resolution — temporal, entity, and alias mapping."""
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.ai.conversation.expense_intent import describes_new_expense
from app.ai.schemas.workflow import ResolvedReferences
from app.ai.expense_extraction import user_description_from_message
from app.ai.workflow.entity_extractor import ExpenseEntityExtractor
from app.ai.workflow.slot_parser import infer_food_sub_category, sanitize_sub_category
from app.models import Expense, ExpenseStatus

_TEMPORAL_PATTERNS = [
    (r"\byesterday\b", "yesterday"),
    (r"\blast\s+time\b", "last"),
    (r"\bprevious\b", "previous"),
    (r"\btoday\b", "today"),
    (r"\blast\s+week\b", "last_week"),
]

_ENTITY_PATTERNS = [
    (r"\bthat\s+expense\b", "that_expense"),
    (r"\bthe\s+expense\b", "that_expense"),
    (r"\blast\s+expense\b", "last_expense"),
    (r"\blast\s+reimbursement\b", "last_reimbursement"),
    (r"\bmy\s+usual\s+payment\s+method\b", "usual_payment"),
    (r"\bsame\s+as\s+yesterday\b", "same_yesterday"),
    (r"\bsame\s+merchant\b", "same_merchant"),
    (r"\bsame\s+category\b", "same_category"),
    (r"\blike\s+last\s+time\b", "like_last_time"),
    (r"\bsame\s+as\s+last\s+time\b", "like_last_time"),
]

_CATEGORY_HINTS = {
    "travel": "travel",
    "lunch": "food",
    "dinner": "food",
    "food": "food",
    "coffee": "food",
    "tea": "food",
    "cafe": "food",
    "uber": "travel",
    "cab": "travel",
    "hotel": "travel",
}


def needs_expense_history(text: str) -> bool:
    """True when the message references prior expenses (temporal / entity aliases)."""
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    for pattern, _ in _TEMPORAL_PATTERNS:
        if re.search(pattern, lowered):
            return True
    for pattern, _ in _ENTITY_PATTERNS:
        if re.search(pattern, lowered):
            return True
    return False


class ReferenceResolver:
    """Resolve conversational references against recent user expenses (no vector DB)."""

    def __init__(self, db: Session):
        self._db = db

    def _recent_expenses(
        self, user_id: int, *, company_id: int, limit: int = 15
    ) -> List[Expense]:
        return (
            self._db.query(Expense)
            .filter(Expense.user_id == user_id, Expense.company_id == company_id)
            .order_by(Expense.bill_date.desc(), Expense.created_at.desc())
            .limit(limit)
            .all()
        )

    def _expense_on_day(self, expenses: List[Expense], day: datetime) -> Optional[Expense]:
        start = day.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        end = start + timedelta(days=1)
        for e in expenses:
            if not e.bill_date:
                continue
            bd = e.bill_date.replace(tzinfo=None) if e.bill_date.tzinfo else e.bill_date
            if start <= bd < end:
                return e
        return None

    def _yesterday(self, now: Optional[datetime] = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        return (now - timedelta(days=1)).replace(tzinfo=None)

    def resolve(self, user_id: int, text: str, *, company_id: int = 1) -> ResolvedReferences:
        lowered = text.strip().lower()
        result = ResolvedReferences()

        if describes_new_expense(text):
            self._extract_new_expense_fields(text, result)

        for pattern, label in _TEMPORAL_PATTERNS:
            if re.search(pattern, lowered):
                result.temporal_label = label
                result.matched_phrases.append(label)
                break

        for pattern, label in _ENTITY_PATTERNS:
            if re.search(pattern, lowered):
                result.matched_phrases.append(label)

        for hint, cat in _CATEGORY_HINTS.items():
            if hint in lowered and not result.main_category:
                result.main_category = cat
                result.matched_phrases.append(f"category_hint:{cat}")

        if not needs_expense_history(text):
            return result

        expenses = self._recent_expenses(user_id, company_id=company_id)
        if not expenses:
            return result

        now = datetime.now(timezone.utc)
        yesterday = self._yesterday(now)

        anchor: Optional[Expense] = None

        if (
            ("same_yesterday" in result.matched_phrases or result.temporal_label == "yesterday")
            and not describes_new_expense(text)
        ):
            anchor = self._expense_on_day(expenses, yesterday)
            if anchor:
                result.notes.append(f"Resolved temporal anchor to expense #{anchor.id} from yesterday.")
        elif "last_expense" in result.matched_phrases or "that_expense" in result.matched_phrases:
            anchor = expenses[0]
            result.notes.append(f"Resolved to most recent expense #{anchor.id}.")
        elif "like_last_time" in result.matched_phrases or "same_merchant" in result.matched_phrases:
            anchor = expenses[0]
            result.notes.append("Resolved 'same as last time' to most recent expense.")

        if anchor:
            result.source_expense_id = anchor.id
            if "same_merchant" in result.matched_phrases or "same_yesterday" in result.matched_phrases:
                if anchor.vendor_name:
                    result.vendor_name = anchor.vendor_name
                elif anchor.bill_name:
                    result.vendor_name = anchor.bill_name
            if "same_category" in result.matched_phrases or "same_yesterday" in result.matched_phrases:
                if anchor.main_category:
                    result.main_category = anchor.main_category.value
                if anchor.sub_category:
                    result.sub_category = anchor.sub_category
            if anchor.payment_method and (
                "usual_payment" in result.matched_phrases or "same_yesterday" in result.matched_phrases
            ):
                result.payment_method = anchor.payment_method.value
            if result.temporal_label == "yesterday" and anchor.bill_name:
                result.bill_name = anchor.bill_name

        if "last_reimbursement" in result.matched_phrases:
            for e in expenses:
                if e.status in (ExpenseStatus.APPROVED, ExpenseStatus.PENDING):
                    result.expense_id = e.id
                    result.notes.append(f"Last reimbursement-related expense #{e.id}.")
                    break

        return result

    def _extract_new_expense_fields(self, text: str, result: ResolvedReferences) -> None:
        """Pull amount, vendor, payment, category, and label from a new-expense description."""
        entities = ExpenseEntityExtractor().extract(text)
        prefill = entities.to_slot_prefill()

        if not result.bill_amount and prefill.get("bill_amount") is not None:
            result.bill_amount = prefill["bill_amount"]
        if not result.vendor_name and prefill.get("vendor_name"):
            result.vendor_name = prefill["vendor_name"]
        if not result.payment_method and prefill.get("payment_method"):
            result.payment_method = prefill["payment_method"]
        if not result.main_category and prefill.get("main_category"):
            result.main_category = prefill["main_category"]
        if not result.bill_name and prefill.get("bill_name"):
            result.bill_name = prefill["bill_name"]
        if not result.description:
            result.description = user_description_from_message(text)

        lowered = text.lower()
        if not result.main_category and any(
            h in lowered
            for h in ("lunch", "dinner", "breakfast", "brunch", "biryani", "restaurant", "pizza")
        ):
            result.main_category = "food"
        if not result.sub_category and result.main_category == "food":
            inferred = infer_food_sub_category(
                vendor_name=result.vendor_name,
                bill_name=result.bill_name,
            )
            if inferred:
                result.sub_category = inferred
        if not result.bill_name:
            for meal in ("lunch", "dinner", "breakfast", "brunch", "biryani"):
                if meal in lowered:
                    result.bill_name = meal.capitalize()
                    break
            if result.vendor_name and not result.bill_name:
                result.bill_name = result.vendor_name
