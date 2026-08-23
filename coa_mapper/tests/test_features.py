from __future__ import annotations

from decimal import Decimal

import pytest

from coa_mapper.features import (
    balance_continuity,
    code_proximity,
    name_similarity,
    token_overlap,
)


def test_name_similarity_identical():
    assert name_similarity("Cash and Cash Equivalents", "Cash and Cash Equivalents") == 1.0


def test_name_similarity_normalized_punctuation():
    score = name_similarity("Property, Plant & Equipment - Cost", "property plant equipment cost")
    assert score > 0.8


def test_name_similarity_disjoint():
    assert name_similarity("Goodwill", "Pension Obligations") < 0.3


def test_token_overlap_partial():
    overlap = token_overlap("Sundry Operating Expenses", "Other Operating Expenses")
    assert abs(overlap - 0.5) < 1e-9


def test_token_overlap_stopwords_ignored():
    assert token_overlap("Cash of the Company", "Cash Company") == 1.0


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("6905", "6900", 0.75),
        ("6905", "6905", 1.0),
        ("1110", "8200", 0.0),
    ],
)
def test_code_proximity(a, b, expected):
    assert code_proximity(a, b) == expected


def test_balance_continuity_close_balances():
    score = balance_continuity(Decimal("132000"), Decimal("140000"))
    assert score == pytest.approx(1 - 8000 / 140000)


def test_balance_continuity_none_when_zero_or_missing():
    assert balance_continuity(None, Decimal("100")) is None
    assert balance_continuity(Decimal("0"), Decimal("100")) is None
    assert balance_continuity(Decimal("50"), None) is None
    assert balance_continuity(None, None) is None


def test_balance_continuity_sign_flip_means_no_continuity():
    assert balance_continuity(Decimal("-132000"), Decimal("132000")) == 0.0
