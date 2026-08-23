"""Chart-of-accounts hierarchy helpers: rollups from leaf accounts to headers."""
from __future__ import annotations
import pandas as pd


def children_of(coa: pd.DataFrame, parent_code: str) -> pd.DataFrame:
    return coa[coa["parent_code"] == parent_code]


def leaf_accounts(coa: pd.DataFrame) -> pd.DataFrame:
    return coa[coa["account_type"] != "Header"]


def rollup(coa: pd.DataFrame, balances: dict, code: str) -> float:
    """Recursively sum an account's own balance plus all descendants' balances.
    `balances` maps account_code -> signed balance (already in normal-balance terms)."""
    row = coa[coa["account_code"] == code]
    total = balances.get(code, 0.0)
    kids = children_of(coa, code)
    for _, kid in kids.iterrows():
        total += rollup(coa, balances, kid["account_code"])
    return total


def headers_with_no_children(coa: pd.DataFrame) -> pd.DataFrame:
    headers = coa[coa["account_type"] == "Header"]
    parents_referenced = set(coa["parent_code"].dropna())
    return headers[~headers["account_code"].isin(parents_referenced)]
