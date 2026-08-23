"""In-process CLI tests.

The failure-contract tests drive the CLI as a subprocess, which is the honest way
to assert a process exit code but leaves cli.py invisible to coverage and leaves
argument handling itself untested. These call main() directly.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from coa_mapper.cli import main
from coa_mapper.pipeline import EXIT_DISCLOSED, EXIT_HARD

INPUTS = Path(__file__).resolve().parents[2] / "inputs"
FILES = ["chart_of_accounts.csv", "fx_rates.csv", "trial_balance.csv", "prior_period_tb.csv"]


@pytest.fixture
def staged(tmp_path):
    inp = tmp_path / "inputs"
    inp.mkdir()
    for name in FILES:
        shutil.copy(INPUTS / name, inp / name)
    return inp


def test_run_returns_disclosed_exit_code(tmp_path, capsys):
    code = main(["run", "--inputs", str(INPUTS), "--out", str(tmp_path / "out")])

    assert code == EXIT_DISCLOSED
    out = capsys.readouterr().out
    assert "PASS WITH DISCLOSED EXCEPTIONS" in out


def test_run_writes_every_artifact(tmp_path):
    out = tmp_path / "out"
    main(["run", "--inputs", str(INPUTS), "--out", str(out)])

    assert {p.name for p in out.iterdir()} == {
        "mapped_tb_current.csv",
        "mapped_tb_prior.csv",
        "review_queue.csv",
        "suspense.csv",
        "decisions.jsonl",
        "validation_report.md",
        "summary.json",
    }


def test_summary_line_reports_per_source_counts(tmp_path, capsys):
    main(["run", "--inputs", str(INPUTS), "--out", str(tmp_path / "out")])
    out = capsys.readouterr().out

    assert "current: auto=58 review=0 suspense=1 total=59" in out
    assert "prior: auto=30 review=1 suspense=0 total=31" in out


def test_cli_flags_override_config_paths(tmp_path, staged, capsys):
    """--inputs/--out must win over whatever config.yaml says."""
    out = tmp_path / "elsewhere"
    code = main(["run", "--inputs", str(staged), "--out", str(out)])

    assert code == EXIT_DISCLOSED
    assert (out / "summary.json").exists()


def test_unreadable_input_returns_hard_failure_not_a_traceback(tmp_path, staged, capsys):
    (staged / "fx_rates.csv").unlink()

    code = main(["run", "--inputs", str(staged), "--out", str(tmp_path / "out")])

    assert code == EXIT_HARD
    err = capsys.readouterr().err
    assert "HARD FAILURE" in err
    assert "FileNotFoundError" in err


def test_failed_run_writes_nothing(tmp_path, staged):
    (staged / "fx_rates.csv").unlink()
    out = tmp_path / "out"

    main(["run", "--inputs", str(staged), "--out", str(out)])

    assert not out.exists() or not list(out.iterdir())


def test_missing_subcommand_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2  # argparse usage error


def test_hard_failure_prints_failed_checks(tmp_path, staged, capsys):
    """A COA cycle fails a check; the operator must see which one."""
    p = staged / "chart_of_accounts.csv"
    p.write_text(
        p.read_text().replace(
            "1100,Current Assets,Header,1000,", "1100,Current Assets,Header,1110,"
        )
    )
    code = main(["run", "--inputs", str(staged), "--out", str(tmp_path / "out")])

    assert code == EXIT_HARD
    assert "errors=" in capsys.readouterr().out
