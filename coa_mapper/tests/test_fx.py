from __future__ import annotations

from decimal import Decimal

from coa_mapper.fx import to_usd


def test_to_usd_rounds_half_up():
    assert to_usd(Decimal("100.005"), Decimal("1")) == Decimal("100.01")
    assert to_usd(Decimal("100.004"), Decimal("1")) == Decimal("100.00")


def test_to_usd_multiplies_then_rounds():
    assert to_usd(Decimal("825400.00"), Decimal("1.095")) == Decimal("903813.00")
    assert to_usd(Decimal("412300.00"), Decimal("1.264")) == Decimal("521147.20")
