"""Hashtag persistence on expense create/update."""
from app.utils.category_hashtags import default_expense_hashtags, normalize_hashtags_list


def test_default_hashtags_food_cafe():
    tags = default_expense_hashtags(
        "food",
        "cafe",
        vendor_name="Cafe Coffee Day",
        bill_name="Coffee",
    )
    assert tags
    assert "food" in tags
    assert "cafe" in tags


def test_normalize_strips_hash():
    assert normalize_hashtags_list(["#food", "cafe"]) == ["food", "cafe"]
