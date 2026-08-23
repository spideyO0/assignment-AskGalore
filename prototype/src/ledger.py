"""Builds the posted general ledger: FX-translated TB rows (mapped accounts only)
plus accepted adjustment lines, aggregated per account with full lineage so every
number can be traced back to source rows / journal entry ids.
"""
from __future__ import annotations
import pandas as pd
from typing import List


def split_mapped_unmapped(tb_translated: pd.DataFrame, coa: pd.DataFrame):
    valid = set(coa["account_code"])
    mapped = tb_translated[tb_translated["account_code"].isin(valid)].copy()
    unmapped = tb_translated[~tb_translated["account_code"].isin(valid)].copy()
    return mapped, unmapped


def detect_duplicate_rows(tb: pd.DataFrame) -> pd.DataFrame:
    """Same account_code + currency appearing more than once. Legitimate summation,
    but flagged because it is also the signature of an accidental double-post."""
    dup_keys = tb.groupby(["account_code", "currency"]).size()
    dup_keys = dup_keys[dup_keys > 1]
    return tb[tb.set_index(["account_code", "currency"]).index.isin(dup_keys.index)]


def build_tb_ledger(mapped_tb: pd.DataFrame) -> pd.DataFrame:
    """Aggregate translated TB rows to one row per account_code, carrying lineage
    (list of source_row indices, currencies, and low_confidence flag)."""
    def agg(group: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "debit_usd": group["debit_usd"].sum(),
            "credit_usd": group["credit_usd"].sum(),
            "source_rows": list(group["source_row"]),
            "currencies": sorted(group["currency"].unique().tolist()),
            "low_confidence": bool(group["low_confidence"].any()),
            "n_source_rows": len(group),
        })
    return mapped_tb.groupby("account_code", as_index=False).apply(agg, include_groups=False)


def apply_adjustments(tb_ledger: pd.DataFrame, entries: list, accepted_ids: set) -> pd.DataFrame:
    """Add accepted JE lines on top of the TB ledger. Returns a new ledger DataFrame
    with an added 'je_refs' lineage column and adjusted debit_usd/credit_usd."""
    ledger = tb_ledger.set_index("account_code").to_dict(orient="index")

    for je in entries:
        if je["id"] not in accepted_ids:
            continue
        for line in je["lines"]:
            acct = line["account"]
            if acct not in ledger:
                ledger[acct] = {
                    "debit_usd": 0.0, "credit_usd": 0.0,
                    "source_rows": [], "currencies": [], "low_confidence": False,
                    "n_source_rows": 0, "je_refs": [],
                }
            ledger[acct].setdefault("je_refs", [])
            ledger[acct]["debit_usd"] = ledger[acct].get("debit_usd", 0.0) + line["debit"]
            ledger[acct]["credit_usd"] = ledger[acct].get("credit_usd", 0.0) + line["credit"]
            ledger[acct]["je_refs"].append(f"{je['id']}:{line['memo']}")

    rows = []
    for acct, vals in ledger.items():
        vals.setdefault("je_refs", [])
        rows.append({"account_code": acct, **vals})
    return pd.DataFrame(rows)


def net_balance(row: pd.Series, normal_balance: str) -> float:
    if normal_balance == "Debit":
        return row["debit_usd"] - row["credit_usd"]
    return row["credit_usd"] - row["debit_usd"]
