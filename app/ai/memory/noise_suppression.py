"""Prevent over-learning and one-off preference poisoning."""
from typing import Optional, Tuple

from app.config import settings
from app.models import Expense, ExpenseStatus


class MemoryNoiseFilter:
    """
    Gate preference observations by status, field completeness, and repetition.
    Returns (should_record, weight) where weight scales learning strength.
    """

    def __init__(
        self,
        *,
        min_weighted_observations_for_prompt: Optional[int] = None,
        min_weighted_observations_for_primary: Optional[int] = None,
        draft_weight: Optional[float] = None,
    ):
        self._min_prompt = (
            min_weighted_observations_for_prompt
            or settings.ai_pref_min_observations_for_prompt
        )
        self._min_primary = (
            min_weighted_observations_for_primary
            or settings.ai_pref_min_observations_for_primary
        )
        self._draft_weight = draft_weight or settings.ai_pref_draft_learning_weight

    @property
    def min_observations_for_prompt(self) -> int:
        return self._min_prompt

    def observation_weight(self, expense: Expense, field: str) -> Tuple[bool, float]:
        if field == "vendor_name":
            if not expense.vendor_name or len(expense.vendor_name.strip()) < 2:
                return False, 0.0
        if field == "payment_method":
            if not expense.payment_method:
                return False, 0.0
        if field == "main_category":
            if not expense.main_category:
                return False, 0.0

        weight = 1.0
        if expense.status == ExpenseStatus.DRAFT:
            weight = self._draft_weight
        elif expense.status in (ExpenseStatus.REJECTED,):
            weight = 0.2

        if expense.bill_amount is not None and expense.bill_amount <= 0:
            weight *= 0.5

        return weight > 0.05, weight

    def can_promote_to_primary(self, weighted_count: float) -> bool:
        return weighted_count >= self._min_primary

    def can_surface_in_prompt(self, weighted_count: float, confidence: float) -> bool:
        return (
            weighted_count >= self._min_prompt
            and confidence >= settings.ai_pref_min_confidence_for_prompt
        )

    def cap_confidence_from_sparse_data(self, confidence: float, weighted_count: float) -> float:
        """One-off observations cannot reach high confidence."""
        if weighted_count < 1.5:
            return min(confidence, 0.35)
        if weighted_count < self._min_primary:
            return min(confidence, 0.65)
        return confidence
