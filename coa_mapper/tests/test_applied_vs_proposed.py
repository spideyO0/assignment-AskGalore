"""A rejected candidate must never read as an applied mapping.

`mapped_tb_*.csv` used to expose one `mapped_code` column populated from the top
candidate regardless of disposition. On the provided data that put
`9999 Suspense - Unmapped` -> `1140 Prepaid Expenses` on the suspense row at
0.3506 confidence, below the 0.60 review floor. Anyone reading
(account_code, mapped_code) off that file would have booked $12,400 of
unidentified suspense into Prepaid Expenses — the exact silent mis-mapping the
confidence gate exists to prevent.

The column is now split: `applied_*` is populated only for AUTO_APPLIED,
`proposed_*` always carries the candidate so the evidence survives.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from pathlib import Path

import pytest

from coa_mapper.config import MapperConfig
from coa_mapper.pipeline import run

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUTS = REPO_ROOT.parent / "inputs"


@pytest.fixture(scope="module")
def artifacts():
    return run(MapperConfig(inputs_dir=INPUTS)).artifacts


def _rows(artifacts, source):
    return list(csv.DictReader(io.StringIO(artifacts[f"mapped_tb_{source}.csv"])))


@pytest.mark.parametrize("source", ["current", "prior"])
def test_applied_columns_are_empty_unless_auto_applied(artifacts, source):
    """The invariant, over every row — not just the ones in this dataset."""
    for row in _rows(artifacts, source):
        if row["disposition"] == "AUTO_APPLIED":
            assert row["applied_code"], f"{row['row_id']} auto-applied with no applied_code"
            assert row["applied_code"] == row["proposed_code"]
        else:
            assert row["applied_code"] == "", (
                f"{row['row_id']} is {row['disposition']} at confidence "
                f"{row['confidence']} but carries applied_code={row['applied_code']!r}"
            )
            assert row["applied_name"] == ""


@pytest.mark.parametrize("source", ["current", "prior"])
def test_no_applied_mapping_below_auto_threshold(artifacts, source):
    """Belt and braces: read the confidence directly, ignore the disposition label."""
    auto_min = MapperConfig().auto_min
    for row in _rows(artifacts, source):
        if row["applied_code"]:
            assert Decimal(row["confidence"]) >= Decimal(str(auto_min)), (
                f"{row['row_id']} applied {row['applied_code']} at {row['confidence']}, "
                f"below auto_min {auto_min}"
            )


def test_suspense_row_keeps_its_evidence_without_claiming_a_mapping(artifacts):
    """The specific regression: 9999 proposes 1140 but must not apply it."""
    row = next(r for r in _rows(artifacts, "current") if r["account_code"] == "9999")

    assert row["disposition"] == "SUSPENSE"
    assert row["applied_code"] == ""
    assert row["applied_name"] == ""
    # evidence preserved, so a reviewer still sees what the matcher considered
    assert row["proposed_code"] == "1140"
    assert row["proposed_name"] == "Prepaid Expenses"
    assert Decimal(row["confidence"]) < Decimal("0.60")


def test_review_row_proposes_without_applying(artifacts):
    """6905 -> 6900 is a proposal awaiting sign-off, not a posted mapping."""
    row = next(r for r in _rows(artifacts, "prior") if r["account_code"] == "6905")

    assert row["disposition"] == "REVIEW"
    assert row["applied_code"] == ""
    assert row["proposed_code"] == "6900"


@pytest.mark.parametrize("source", ["current", "prior"])
def test_applied_column_never_resurrects_a_suspense_dollar(artifacts, source):
    """Summing by applied_code must reproduce the AUTO_APPLIED total exactly, so no
    suspense or review dollar can leak into a downstream mapping table."""
    rows = _rows(artifacts, source)
    applied_usd = sum(
        Decimal(r["usd_debit"]) - Decimal(r["usd_credit"]) for r in rows if r["applied_code"]
    )
    auto_usd = sum(
        Decimal(r["usd_debit"]) - Decimal(r["usd_credit"])
        for r in rows
        if r["disposition"] == "AUTO_APPLIED"
    )
    assert applied_usd == auto_usd


def test_header_has_no_ambiguous_mapped_column(artifacts):
    """Guard the naming itself: a bare `mapped_code` invites the original misread."""
    header = artifacts["mapped_tb_current.csv"].splitlines()[0].split(",")
    assert "mapped_code" not in header
    assert "mapped_name" not in header
    for col in ("applied_code", "applied_name", "proposed_code", "proposed_name"):
        assert col in header
