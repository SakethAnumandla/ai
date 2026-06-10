"""Query/body transaction_type aliases used by the Flutter app."""
import pytest

from app.utils.transaction_parser import coerce_transaction_type, parse_transaction_type
from app.models import TransactionType
from fastapi import HTTPException


def test_coerce_expense_aliases():
    assert coerce_transaction_type("out") == TransactionType.EXPENSE
    assert coerce_transaction_type("expense") == TransactionType.EXPENSE
    assert coerce_transaction_type(None) is None
    assert coerce_transaction_type("") is None


def test_coerce_income_aliases():
    assert coerce_transaction_type("in") == TransactionType.INCOME
    assert coerce_transaction_type("income") == TransactionType.INCOME


def test_coerce_invalid_raises():
    with pytest.raises(ValueError, match="Invalid transaction_type"):
        coerce_transaction_type("not-a-type")


def test_parse_transaction_type_http_exception():
    with pytest.raises(HTTPException) as exc:
        parse_transaction_type("bad-value")
    assert exc.value.status_code == 400
