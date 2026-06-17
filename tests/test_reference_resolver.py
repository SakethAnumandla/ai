"""Reference resolver — avoid loading expense history for simple chat."""
from app.ai.resolution.reference_resolver import needs_expense_history, ReferenceResolver


def test_needs_expense_history_for_temporal_and_entity_phrases():
    assert needs_expense_history("same as yesterday")
    assert needs_expense_history("that expense from last week")
    assert not needs_expense_history("hello")
    assert not needs_expense_history("create a manual expense")


def test_resolve_skips_db_for_greeting(monkeypatch):
    resolver = ReferenceResolver(db=object())  # type: ignore[arg-type]

    def _boom(*_args, **_kwargs):
        raise AssertionError("expense history should not be queried for greetings")

    monkeypatch.setattr(resolver, "_recent_expenses", _boom)
    result = resolver.resolve(1, "hello", company_id=12)
    assert result.matched_phrases == []
