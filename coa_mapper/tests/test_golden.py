from __future__ import annotations

from pathlib import Path

import pytest

from coa_mapper.config import MapperConfig
from coa_mapper.pipeline import run

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUTS = REPO_ROOT.parent / "inputs"
GOLDEN = REPO_ROOT / "tests" / "golden"

GOLDEN_FILES = [
    "mapped_tb_current.csv",
    "mapped_tb_prior.csv",
    "review_queue.csv",
    "suspense.csv",
    "decisions.jsonl",
    "validation_report.md",
    "summary.json",
]


@pytest.fixture(scope="module")
def artifacts():
    return run(MapperConfig(inputs_dir=INPUTS)).artifacts


@pytest.mark.parametrize("name", GOLDEN_FILES)
def test_output_matches_golden(artifacts, name):
    expected = (GOLDEN / name).read_text()
    assert artifacts[name] == expected, f"{name} drifted from golden baseline"
