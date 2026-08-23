"""Deterministic loaders for the four source files. No interpretation happens here,
just parsing and type coercion. Anything that looks wrong is reported, never silently fixed."""
from __future__ import annotations
import json
import pandas as pd
from pathlib import Path

INPUTS = Path(__file__).resolve().parents[2] / "inputs"


def load_coa() -> pd.DataFrame:
    df = pd.read_csv(INPUTS / "chart_of_accounts.csv", dtype={"account_code": str, "parent_code": str})
    df["account_code"] = df["account_code"].str.strip()
    df["parent_code"] = df["parent_code"].str.strip()
    return df


def load_trial_balance() -> pd.DataFrame:
    df = pd.read_csv(INPUTS / "trial_balance.csv", dtype={"account_code": str})
    df["account_code"] = df["account_code"].str.strip()
    df["source_row"] = df.index  # stable handle for audit trail
    return df


def load_prior_trial_balance() -> pd.DataFrame:
    df = pd.read_csv(INPUTS / "prior_period_tb.csv", dtype={"account_code": str})
    df["account_code"] = df["account_code"].str.strip()
    return df


def load_fx_rates() -> pd.DataFrame:
    return pd.read_csv(INPUTS / "fx_rates.csv")


def load_adjustments() -> dict:
    with open(INPUTS / "manual_adjustments.json", "r", encoding="utf-8") as f:
        return json.load(f)
