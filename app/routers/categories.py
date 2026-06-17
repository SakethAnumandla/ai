"""Manual category picker and hashtag recommendations."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.deps.scope import ExpenseScope, get_expense_scope
from app.utils.category_hashtags import (
    MANUAL_CATEGORY_VALUES,
    get_hashtag_recommendations,
    get_manual_categories_payload,
)
from app.utils.payment_modes import list_payment_modes

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("/business/hierarchy")
async def business_taxonomy_hierarchy(
    _scope: ExpenseScope = Depends(get_expense_scope),
):
    """Full business category tree (travel, food, office, …)."""
    from app.data.business_taxonomy import get_taxonomy_hierarchy

    return get_taxonomy_hierarchy()


@router.get("/manual")
async def list_manual_categories(
    _scope: ExpenseScope = Depends(get_expense_scope),
):
    """
    Main categories for manual expense entry
    (travel, food, utilities, fuel, shopping, subscriptions).
    """
    payload = get_manual_categories_payload()
    pm = list_payment_modes()
    payload["payment_modes"] = pm["payment_modes"]
    payload["default_payment_mode"] = pm["default"]
    return payload


@router.get("/{category}/hashtags")
async def get_category_hashtags(
    category: str,
    sub_category: Optional[str] = None,
    _scope: ExpenseScope = Depends(get_expense_scope),
):
    """
    AI-style hashtag suggestions for a selected main category.
    Example: GET /categories/food/hashtags → food, vegfood, …
    """
    key = category.lower().strip()
    if key not in MANUAL_CATEGORY_VALUES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown category '{category}'. Use GET /categories/manual for valid values.",
        )
    return get_hashtag_recommendations(key, sub_category)
