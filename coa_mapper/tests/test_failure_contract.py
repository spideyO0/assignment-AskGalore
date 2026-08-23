"""Regression tests for five defects found by probing malformed inputs.

Each class covers one fix. Every test asserts the invariant, not the value it
happens to take on the provided dataset.
"""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from coa_mapper.coa import structural_findings
from coa_mapper.config import MapperConfig
from coa_mapper.io_loaders import load_coa
from coa_mapper.pipeline import EXIT_DISCLOSED, EXIT_HARD, run

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUTS = REPO_ROOT.parent / "inputs"
FILES = ["chart_of_accounts.csv", "fx_rates.csv", "trial_balance.csv", "prior_period_tb.csv"]


@pytest.fixture
def staged(tmp_path):
    """A private copy of the real inputs, to be mutated one field at a time."""
    inp = tmp_path / "inputs"
    inp.mkdir()
    for name in FILES:
        shutil.copy(INPUTS / name, inp / name)
    return inp


def cli(inp: Path, out: Path):
    return subprocess.run(
        [sys.executable, "-m", "coa_mapper.cli", "run", "--inputs", str(inp), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT / "src",
        check=False,
    )


def findings_with(outcome, code: str):
    return [f for f in outcome.findings if f.code == code]


# ---------------------------------------------------------------- fix 1


class TestExitCodeContract:
    """A run that cannot complete must exit 2, never 1.

    `run()` was called with no exception handling, so an unreadable input escaped
    as an uncaught traceback and Python exited 1 — the code documented as "PASS
    WITH DISCLOSED EXCEPTIONS". CI wired "fail on 2, review on 1" read a missing
    trial balance as a successful run needing review.
    """

    def test_missing_input_file_exits_hard_not_disclosed(self, staged, tmp_path):
        (staged / "trial_balance.csv").unlink()
        proc = cli(staged, tmp_path / "out")

        assert proc.returncode == EXIT_HARD
        assert proc.returncode != EXIT_DISCLOSED, "a failure must never claim disclosed exceptions"

    def test_missing_input_file_reports_cleanly_without_a_traceback(self, staged, tmp_path):
        (staged / "trial_balance.csv").unlink()
        proc = cli(staged, tmp_path / "out")

        assert "Traceback (most recent call last)" not in proc.stderr
        assert "HARD FAILURE" in proc.stderr
        assert "FileNotFoundError" in proc.stderr, "the cause must survive into the message"

    def test_unreadable_input_writes_no_partial_artifacts(self, staged, tmp_path):
        (staged / "trial_balance.csv").unlink()
        out = tmp_path / "out"
        cli(staged, out)

        assert not out.exists() or not list(out.iterdir())


# ---------------------------------------------------------------- fix 2


class TestPartiallyTranslatableAccount:
    """An account with one untranslatable row must not lose the rows that did
    translate, and must not be dispositioned twice.

    The stub hardcoded usd_net=0, so suspense reported $0.00 for an account
    holding $1,424,960.20; and the translatable aggregate still produced its own
    decision, so the account was counted twice and USD conservation broke.
    """

    @pytest.fixture
    def mixed(self, staged):
        """1110 keeps its EUR and GBP rows; its USD row becomes unrateable JPY."""
        p = staged / "trial_balance.csv"
        lines = p.read_text().splitlines()
        lines[1] = lines[1].replace(",USD,", ",JPY,")
        p.write_text("\n".join(lines) + "\n")
        return run(MapperConfig(inputs_dir=staged))

    def test_account_receives_exactly_one_decision(self, mixed):
        codes = [d.account_code for d in mixed.decisions if d.source == "current"]
        assert codes.count("1110") == 1, "partly-untranslatable account dispositioned twice"
        assert len(codes) == len(set(codes))

    def test_suspense_carries_the_translatable_subtotal_not_zero(self, mixed):
        dec = next(d for d in mixed.decisions if d.source == "current" and d.account_code == "1110")

        assert dec.disposition == "SUSPENSE"
        # EUR 825400 x 1.095 + GBP 412300 x 1.264
        assert dec.usd_net == Decimal("1424960.20")

    def test_reason_states_the_figure_is_partial(self, mixed):
        dec = next(d for d in mixed.decisions if d.source == "current" and d.account_code == "1110")
        reason = " ".join(dec.reasons).lower()

        assert "jpy" in reason, "the unrateable currency must be named"
        assert (
            "partial" in reason or "understates" in reason
        ), "a partial figure presented without qualification is a wrong figure"

    def test_usd_conservation_holds(self, mixed):
        failed = [name for name, passed, _ in mixed.checks if not passed]
        assert "current:usd_conservation" not in failed
        assert "current:row_conservation" not in failed

    def test_every_row_of_the_account_is_still_claimed(self, mixed):
        dec = next(d for d in mixed.decisions if d.source == "current" and d.account_code == "1110")
        assert set(dec.row_ids) == {"current:2", "current:3", "current:4"}

    def test_wholly_untranslatable_account_states_no_amount(self, staged):
        """No portion translatable — then $0.00 is honest, and must say so."""
        p = staged / "trial_balance.csv"
        lines = p.read_text().splitlines()
        lines = [lines[0], lines[1].replace(",USD,", ",JPY,")] + lines[4:]
        p.write_text("\n".join(lines) + "\n")
        outcome = run(MapperConfig(inputs_dir=staged, sources=("current",)))

        dec = next(d for d in outcome.decisions if d.account_code == "1110")
        assert dec.usd_net == Decimal("0.00")
        assert "no dollar amount can be stated" in " ".join(dec.reasons)


class TestVerifierIndependence:
    """usd_conservation must test the artifact, not the verifier's own re-derivation.

    The verifier overwrote the pipeline's claimed decisions with its own stubs
    before summing, so a wrong usd_net in the output could not fail the check.
    """

    def test_conservation_compares_claimed_figures(self, staged):
        outcome = run(MapperConfig(inputs_dir=staged))
        claimed = sum(
            (abs(d.usd_net) for d in outcome.decisions if d.source == "current"), Decimal("0")
        )
        detail = next(d for n, _, d in outcome.checks if n == "current:usd_conservation")

        assert str(claimed) in detail, "the check must quote the claimed total it compared"


# ---------------------------------------------------------------- fix 3


class TestCoaCycleDetection:
    """A parent cycle is fatal to any rollup and was reported by nothing.

    The structural checks were all single-node — child counts and parentless
    leaves — so no parent chain was ever walked.
    """

    def _coa_with_cycle(self, staged):
        p = staged / "chart_of_accounts.csv"
        p.write_text(
            p.read_text().replace(
                "1100,Current Assets,Header,1000,", "1100,Current Assets,Header,1110,"
            )
        )
        return staged

    def test_cycle_is_reported_as_an_error(self, staged):
        outcome = run(MapperConfig(inputs_dir=self._coa_with_cycle(staged)))
        found = findings_with(outcome, "COA_PARENT_CYCLE")

        assert found, "1100 -> 1110 -> 1100 went unreported"
        assert all(f.severity.value == "ERROR" for f in found)

    def test_cycle_forces_a_hard_failure(self, staged):
        outcome = run(MapperConfig(inputs_dir=self._coa_with_cycle(staged)))
        assert outcome.exit_code == EXIT_HARD

    def test_cycle_message_names_the_loop(self, staged):
        outcome = run(MapperConfig(inputs_dir=self._coa_with_cycle(staged)))
        msg = findings_with(outcome, "COA_PARENT_CYCLE")[0].message

        assert "1100" in msg and "1110" in msg

    def test_self_parent_is_a_cycle(self, staged):
        p = staged / "chart_of_accounts.csv"
        p.write_text(
            p.read_text().replace(
                "1100,Current Assets,Header,1000,", "1100,Current Assets,Header,1100,"
            )
        )
        outcome = run(MapperConfig(inputs_dir=staged))
        assert findings_with(outcome, "COA_PARENT_CYCLE")

    def test_each_cycle_reported_once_not_once_per_member(self, staged):
        """Three nodes in one loop is one finding, not three."""
        p = staged / "chart_of_accounts.csv"
        t = p.read_text()
        t = t.replace("1000,Total Assets,Header,,", "1000,Total Assets,Header,1200,")
        t = t.replace("1100,Current Assets,Header,1000,", "1100,Current Assets,Header,1000,")
        t = t.replace(
            "1200,Non-Current Assets,Header,1000,", "1200,Non-Current Assets,Header,1100,"
        )
        p.write_text(t)
        outcome = run(MapperConfig(inputs_dir=staged))

        assert len(findings_with(outcome, "COA_PARENT_CYCLE")) == 1

    def test_clean_chart_reports_no_cycle(self):
        nodes = load_coa(INPUTS / "chart_of_accounts.csv")[0]
        assert not [f for f in structural_findings(nodes) if f.code == "COA_PARENT_CYCLE"]

    def test_missing_parent_is_reported_but_is_not_fatal(self, staged):
        """An unreachable subtree is a data problem; it does not break a rollup."""
        p = staged / "chart_of_accounts.csv"
        p.write_text(
            p.read_text().replace(
                "1110,Cash and Cash Equivalents,Asset,1100,",
                "1110,Cash and Cash Equivalents,Asset,9500,",
            )
        )
        outcome = run(MapperConfig(inputs_dir=staged))

        assert findings_with(outcome, "COA_PARENT_MISSING")
        assert outcome.exit_code == EXIT_DISCLOSED


# ---------------------------------------------------------------- fix 4


class TestSuspenseRateEscalation:
    """Total mapping collapse must not report as routine review workload.

    Exit codes were presence-based, so one suspense row and every suspense row
    were indistinguishable: a COA with no usable targets sent 90/90 accounts to
    suspense and still exited 1.
    """

    @pytest.fixture
    def headers_only(self, staged):
        p = staged / "chart_of_accounts.csv"
        lines = p.read_text().splitlines()
        p.write_text("\n".join([lines[0]] + [x for x in lines[1:] if ",Header," in x]) + "\n")
        return staged

    def test_total_collapse_is_a_hard_failure(self, headers_only):
        outcome = run(MapperConfig(inputs_dir=headers_only))
        assert outcome.exit_code == EXIT_HARD

    def test_collapse_finding_quotes_both_ratios(self, headers_only):
        outcome = run(MapperConfig(inputs_dir=headers_only))
        msgs = [f.message for f in findings_with(outcome, "SUSPENSE_RATE_EXCEEDED")]

        assert msgs
        assert any("100.0%" in m and "59/59" in m for m in msgs)

    def test_nothing_is_dropped_even_when_escalated(self, headers_only):
        """Escalation is about the exit code; conservation must still hold."""
        outcome = run(MapperConfig(inputs_dir=headers_only))
        failed = [name for name, passed, _ in outcome.checks if not passed]

        assert "current:row_conservation" not in failed
        assert "current:usd_conservation" not in failed

    def test_normal_run_stays_below_the_limit(self):
        outcome = run(MapperConfig(inputs_dir=INPUTS))
        assert not findings_with(outcome, "SUSPENSE_RATE_EXCEEDED")
        assert outcome.exit_code == EXIT_DISCLOSED

    def test_threshold_is_configurable(self):
        """One suspense account in 59 trips a 1% limit."""
        outcome = run(MapperConfig(inputs_dir=INPUTS, max_suspense_ratio=0.01))
        assert findings_with(outcome, "SUSPENSE_RATE_EXCEEDED")
        assert outcome.exit_code == EXIT_HARD

    def test_threshold_is_echoed_into_the_report(self):
        outcome = run(MapperConfig(inputs_dir=INPUTS))
        assert "max_suspense_ratio" in outcome.artifacts["validation_report.md"]


# ---------------------------------------------------------------- fix 5


class TestScoreReproducibleFromPublishedEvidence:
    """The published confidence must be recomputable from the published features.

    Confidence was derived from full-precision floats while the feature vector was
    rounded separately, so 9999 published name_similarity 0.5455 (6/11 unrounded)
    alongside a confidence of 0.3506 — recomputing gives 0.3507. An audit trail
    whose numbers do not reconcile with each other is not an audit trail.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def outcome(cls):
        return run(MapperConfig(inputs_dir=INPUTS))

    @staticmethod
    def _recompute(decision) -> Decimal:
        num = sum(
            Decimal(str(v)) * Decimal(str(decision.weights_used[k]))
            for k, v in decision.features.items()
        )
        den = sum(Decimal(str(decision.weights_used[k])) for k in decision.features)
        return (num / den).quantize(Decimal("0.0001"))

    def test_every_scored_decision_reconciles_with_its_own_features(self, outcome):
        scored = [d for d in outcome.decisions if d.tier == "FUZZY_COMPOSITE" and d.features]
        assert scored, "no fuzzy decisions to check"
        for d in scored:
            assert self._recompute(d) == d.confidence, (
                f"{d.source}:{d.account_code} publishes {d.confidence} but its own "
                f"feature vector recomputes to {self._recompute(d)}"
            )

    def test_the_regression_case_reconciles(self, outcome):
        d = next(x for x in outcome.decisions if x.account_code == "9999")
        assert d.features["name_similarity"] == 0.5455
        assert d.confidence == Decimal("0.3507")
        assert self._recompute(d) == d.confidence

    def test_margin_is_the_difference_of_the_two_printed_confidences(self, outcome):
        for d in outcome.decisions:
            if d.runner_up_code:
                assert d.margin == d.confidence - d.runner_up_confidence

    def test_features_are_published_at_the_precision_they_were_scored_at(self, outcome):
        for d in outcome.decisions:
            for k, v in d.features.items():
                assert Decimal(str(v)) == Decimal(str(v)).quantize(
                    Decimal("0.0001")
                ), f"{d.account_code}.{k}={v} carries precision the score did not use"

    def test_review_queue_margin_reconciles_in_the_artifact(self, outcome):
        rows = list(csv.DictReader(io.StringIO(outcome.artifacts["review_queue.csv"])))
        assert rows
        for r in rows:
            assert Decimal(r["margin"]) == Decimal(r["confidence"]) - Decimal(
                r["runner_up_confidence"]
            )


# ---------------------------------------------------------------- fix 6


class TestThresholdConstructionIsShared:
    """Pipeline and verifier must gate on identical threshold values.

    They built MatchConfig separately: the pipeline wrapped thresholds in Decimal,
    the verifier passed raw floats. float 0.90 is 0.9000000000000000222, so a
    candidate scoring exactly 0.9000 auto-applied in one and went to REVIEW in the
    other — decision_reproduction would report a divergence and exit 2 on a
    perfectly good mapping. No account hits 0.9000 on the provided data, which is
    the only reason it never fired.
    """

    def test_float_threshold_would_have_diverged_at_the_boundary(self):
        """The bug this guards against is real arithmetic, not a hypothetical."""
        exactly_at_threshold = Decimal("0.9000")
        assert exactly_at_threshold >= Decimal("0.90")
        assert not (exactly_at_threshold >= 0.90)  # noqa: SIM300 - float is the point

    def test_both_call_sites_produce_decimal_thresholds(self):
        from coa_mapper.matcher import match_config_from

        cfg = match_config_from(MapperConfig())
        assert isinstance(cfg.auto_min, Decimal)
        assert isinstance(cfg.review_min, Decimal)
        assert cfg.auto_min == Decimal("0.90")

    def test_a_candidate_exactly_at_auto_min_is_gated_identically(self):
        from coa_mapper.matcher import match_config_from

        cfg = match_config_from(MapperConfig())
        score = Decimal("0.9000")
        assert (score >= cfg.auto_min) is True, "boundary score must auto-apply, not review"

    def test_verifier_reproduces_every_decision_on_the_real_data(self):
        outcome = run(MapperConfig(inputs_dir=INPUTS))
        diverged = [n for n, passed, _ in outcome.checks if not passed and "reproduction" in n]
        assert not diverged
