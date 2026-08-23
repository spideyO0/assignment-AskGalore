from __future__ import annotations

from pathlib import Path

from coa_mapper.config import MapperConfig
from coa_mapper.pipeline import EXIT_HARD, run


def write_inputs(tmp_path: Path, tb_text: str) -> Path:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = Path(__file__).resolve().parents[1].parent / "inputs"
    for name in ["chart_of_accounts.csv", "fx_rates.csv", "prior_period_tb.csv"]:
        (inputs / name).write_text((source / name).read_text())
    (inputs / "trial_balance.csv").write_text(tb_text)
    return inputs


GOOD_TB = """account_code,account_name,currency,debit,credit
1110,Cash and Cash Equivalents,USD,1000.00,0.00
6900,Other Operating Expenses,USD,0.00,250.00
"""


def test_bad_numeric_amount_is_hard_failure(tmp_path):
    bad = GOOD_TB + "1120,Accounts Receivable,USD,not-a-number,0.00\n"
    inputs = write_inputs(tmp_path, bad)
    outcome = run(MapperConfig(inputs_dir=inputs))
    assert outcome.exit_code == EXIT_HARD
    codes = {f.code for f in outcome.findings}
    assert "SCHEMA_BAD_NUMBER" in codes


def test_missing_column_is_hard_failure(tmp_path):
    broken = "account_code,account_name,currency,debit\n1110,Cash,USD,10.00\n"
    inputs = write_inputs(tmp_path, broken)
    outcome = run(MapperConfig(inputs_dir=inputs))
    assert outcome.exit_code == EXIT_HARD


def test_unknown_currency_routed_to_suspense_with_error(tmp_path):
    tb = GOOD_TB + "1150,Other Current Assets,JPY,500.00,0.00\n"
    inputs = write_inputs(tmp_path, tb)
    outcome = run(MapperConfig(inputs_dir=inputs))
    codes = {(d.source, d.account_code): d for d in outcome.decisions}
    jpy = codes[("current", "1150")]
    assert jpy.disposition == "SUSPENSE"
    assert "NO_FX_RATE" in jpy.flags
    assert any(f.code == "CURRENCY_NO_RATE" for f in outcome.findings)


def test_clean_dataset_exits_zero(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "chart_of_accounts.csv").write_text(
        "account_code,account_name,account_type,parent_code,statement,cf_category,"
        "normal_balance\n"
        "1000,Total Assets,Header,,BS,,Debit\n"
        "1100,Cash and Cash Equivalents,Asset,1000,BS,Cash,Debit\n"
        "2000,Total Expenses,Header,,PL,,Debit\n"
        "2100,Other Operating Expenses,Expense,2000,PL,Operating,Debit\n"
    )
    (inputs / "fx_rates.csv").write_text(
        "currency,rate_type,rate,period\nUSD,period_end,1.0,2024-Q4\n"
    )
    (inputs / "trial_balance.csv").write_text(
        "account_code,account_name,currency,debit,credit\n"
        "1100,Cash and Cash Equivalents,USD,1000.00,0.00\n"
        "2100,Other Operating Expenses,USD,0.00,250.00\n"
    )
    outcome = run(MapperConfig(inputs_dir=inputs, sources=("current",)))
    assert outcome.exit_code == 0
    assert all(p for _, p, _ in outcome.checks)
