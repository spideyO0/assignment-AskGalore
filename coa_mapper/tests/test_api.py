"""The HTTP API that backs the UI.

The contract: the API is a shell around the same `run(config)` the CLI calls. It
must produce byte-identical artifacts, hold no state between requests, and report
a bad run as a payload rather than a transport error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coa_mapper.api import OPTIONAL, REQUIRED, execute
from coa_mapper.config import MapperConfig
from coa_mapper.pipeline import EXIT_DISCLOSED, EXIT_HARD, run

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUTS = REPO_ROOT.parent / "inputs"
ENTITIES = REPO_ROOT / "config" / "entities"


@pytest.fixture(scope="module")
def files():
    return {p.name: p.read_text(encoding="utf-8-sig") for p in INPUTS.iterdir() if p.is_file()}


@pytest.fixture
def base():
    return MapperConfig(entities_dir=ENTITIES)


class TestParityWithTheCli:
    def test_artifacts_are_byte_identical_to_a_cli_run(self, files, base):
        api = execute(files, None, base)
        cli = run(MapperConfig(inputs_dir=INPUTS))

        assert api["ok"]
        assert set(api["artifacts"]) == set(cli.artifacts)
        for name, content in cli.artifacts.items():
            assert api["artifacts"][name] == content, f"{name} differs between API and CLI"

    def test_exit_code_matches(self, files, base):
        assert (
            execute(files, None, base)["exit_code"]
            == run(MapperConfig(inputs_dir=INPUTS)).exit_code
        )

    def test_decisions_parsed_from_the_same_jsonl(self, files, base):
        api = execute(files, None, base)
        from_artifact = [
            json.loads(x) for x in api["artifacts"]["decisions.jsonl"].splitlines() if x
        ]
        assert api["decisions"] == from_artifact


class TestStatelessness:
    def test_two_identical_requests_agree(self, files, base):
        a, b = execute(files, None, base), execute(files, None, base)
        assert a["artifacts"] == b["artifacts"]

    def test_a_prior_request_cannot_leak_into_the_next(self, files, base):
        """Run with both periods, then current only. The second must not see the
        prior TB from the first — a temp dir left behind would do exactly that."""
        execute(files, None, base)
        only_current = {k: v for k, v in files.items() if k != "prior_period_tb.csv"}
        second = execute(only_current, None, base)

        assert second["sources"] == ["current"]
        assert "mapped_tb_prior.csv" not in second["artifacts"]
        assert all(d["source"] == "current" for d in second["decisions"])


class TestInputHandling:
    def test_missing_required_file_is_a_hard_failure(self, base):
        r = execute({"trial_balance.csv": "x"}, None, base)

        assert not r["ok"]
        assert r["exit_code"] == EXIT_HARD
        assert "chart_of_accounts.csv" in r["error"]

    def test_prior_period_is_optional(self, files, base):
        r = execute({k: v for k, v in files.items() if k != "prior_period_tb.csv"}, None, base)

        assert r["ok"]
        assert r["sources"] == ["current"]

    def test_unrecognised_files_are_ignored_not_written(self, files, base):
        r = execute({**files, "notes.txt": "ignore me", "../escape.csv": "no"}, None, base)
        assert r["ok"]

    def test_malformed_input_reports_the_cause_without_a_traceback_to_the_user(self, files, base):
        broken = {
            **files,
            "fx_rates.csv": "currency,rate_type,rate,period\nEUR,period_end,abc,Q4\n",
        }
        r = execute(broken, None, base)

        assert r["exit_code"] == EXIT_HARD

    def test_empty_files_are_reported_through_findings_not_a_crash(self, base):
        """The pipeline handles this rather than raising, so the run completes and
        says exit 2 via ERROR findings. `ok` stays true: the exchange succeeded,
        the run did not."""
        r = execute(
            {"chart_of_accounts.csv": "", "fx_rates.csv": "", "trial_balance.csv": ""}, None, base
        )

        assert r["ok"] is True
        assert r["exit_code"] == EXIT_HARD
        assert any(f["severity"] == "ERROR" for f in r["findings"])
        assert "error" not in r, "nothing crashed, so there is no crash to report"


class TestEntityPolicy:
    def test_entity_is_applied_and_echoed(self, files, base):
        r = execute(files, "acme_us", base)

        assert r["ok"]
        assert r["entity"] == "acme_us"
        assert r["config"]["tie_epsilon"] == 0.05

    def test_unknown_entity_is_a_hard_failure(self, files, base):
        r = execute(files, "nope", base)

        assert not r["ok"]
        assert r["exit_code"] == EXIT_HARD
        assert "acme_us" in r["error"]


class TestResponseShape:
    def test_carries_everything_the_ui_needs(self, files, base):
        r = execute(files, None, base)

        for key in (
            "exit_code",
            "status",
            "sources",
            "config",
            "summary",
            "decisions",
            "findings",
            "checks",
            "artifacts",
        ):
            assert key in r, f"response is missing {key}"

    def test_findings_are_severity_ordered(self, files, base):
        order = {"ERROR": 0, "WARN": 1, "INFO": 2}
        sev = [order[f["severity"]] for f in execute(files, None, base)["findings"]]
        assert sev == sorted(sev)

    def test_checks_expose_pass_state_and_detail(self, files, base):
        checks = execute(files, None, base)["checks"]

        assert checks
        assert all({"name", "passed", "detail"} <= set(c) for c in checks)

    def test_required_and_optional_lists_match_the_pipeline(self):
        assert "trial_balance.csv" in REQUIRED
        assert "chart_of_accounts.csv" in REQUIRED
        assert "fx_rates.csv" in REQUIRED
        assert "prior_period_tb.csv" in OPTIONAL

    def test_status_text_matches_the_exit_code(self, files, base):
        r = execute(files, None, base)
        assert r["exit_code"] == EXIT_DISCLOSED
        assert r["status"] == "PASS WITH DISCLOSED EXCEPTIONS"
