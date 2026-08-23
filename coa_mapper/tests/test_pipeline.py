from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from coa_mapper.config import MapperConfig
from coa_mapper.pipeline import run, write_artifacts

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUTS = REPO_ROOT.parent / "inputs"


@pytest.fixture(scope="module")
def outcome():
    config = MapperConfig(
        inputs_dir=INPUTS,
        output_dir=REPO_ROOT / "output_test_run",
    )
    return run(config)


def test_exit_code_is_disclosed_exceptions(outcome):
    assert outcome.exit_code == 1


def test_row_conservation_every_input_row_accounted_once(outcome):
    by_source: dict[str, set[str]] = {}
    for decision in outcome.decisions:
        seen = by_source.setdefault(decision.source, set())
        for rid in decision.row_ids:
            assert rid not in seen, f"row {rid} claimed twice"
            seen.add(rid)
    expected = {"current": 62, "prior": 33}
    for source, count in expected.items():
        assert len(by_source[source]) == count


def test_seeded_defects_dispositioned(outcome):
    codes = {(d.source, d.account_code): d for d in outcome.decisions}
    suspense = codes[("current", "9999")]
    assert suspense.disposition == "SUSPENSE"
    assert suspense.usd_net == Decimal("12400.00")
    review = codes[("prior", "6905")]
    assert review.disposition == "REVIEW"
    assert review.mapped_code == "6900"
    dup = [f for f in outcome.findings if f.code == "DUP_ACCOUNT_CURRENCY"]
    assert any("6310" in f.message for f in dup)
    fallbacks = [f for f in outcome.findings if f.code == "FX_PERIOD_END_FALLBACK"]
    assert any("GBP" in f.message for f in fallbacks)


def test_all_checks_pass(outcome):
    failed = [(n, d) for n, p, d in outcome.checks if not p]
    assert failed == []


def test_written_artifacts_byte_stable_across_runs(tmp_path):
    config_a = MapperConfig(inputs_dir=INPUTS, output_dir=tmp_path / "a")
    config_b = MapperConfig(inputs_dir=INPUTS, output_dir=tmp_path / "b")
    artifacts_a = run(config_a).artifacts
    artifacts_b = run(config_b).artifacts
    assert artifacts_a.keys() == artifacts_b.keys()
    for name in artifacts_a:
        assert artifacts_a[name] == artifacts_b[name], f"{name} not byte-identical"


def test_write_artifacts_produces_files(tmp_path, outcome):
    written = write_artifacts(outcome.artifacts, tmp_path)
    assert len(written) == len(outcome.artifacts)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["run_status"] == "PASS_WITH_DISCLOSED_EXCEPTIONS"
    report = (tmp_path / "validation_report.md").read_text()
    assert "Reconciliation math" in report
