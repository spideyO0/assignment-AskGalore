"""FX translation of trial-balance rows into functional currency (USD).

Policy (documented, not silently applied):
  - Balance-sheet monetary balances translate at the PERIOD-END rate.
  - USD rows pass through at 1.0.
  - If a currency has no period-end rate published, we do NOT invent one.
    We fall back to the period-average rate as a provisional value, and we
    flag every row translated this way as low_confidence=True so it surfaces
    in the validation report and can be corrected once Treasury publishes
    the missing rate. This mirrors what a human controller would actually do:
    close the books provisionally, disclose the assumption, and do not block.
"""
from __future__ import annotations
import pandas as pd

from typing import Tuple


def build_rate_table(fx: pd.DataFrame) -> dict:
    """currency -> {'period_end': x or None, 'period_average': y or None}"""
    table: dict = {}
    for _, row in fx.iterrows():
        table.setdefault(row["currency"], {})[row["rate_type"]] = row["rate"]
    return table


def translate_tb(tb: pd.DataFrame, fx: pd.DataFrame) -> Tuple[pd.DataFrame, list]:
    """Returns (translated_df, warnings). translated_df gains debit_usd/credit_usd,
    rate_used, rate_source, low_confidence columns."""
    rates = build_rate_table(fx)
    warnings = []

    out = tb.copy()
    rate_used, rate_source, low_conf = [], [], []

    for _, row in tb.iterrows():
        ccy = row["currency"]
        if ccy == "USD":
            rate_used.append(1.0)
            rate_source.append("identity")
            low_conf.append(False)
            continue

        ccy_rates = rates.get(ccy, {})
        pe = ccy_rates.get("period_end")
        if pe is not None and not pd.isna(pe):
            rate_used.append(pe)
            rate_source.append("period_end")
            low_conf.append(False)
        else:
            avg = ccy_rates.get("period_average")
            if avg is None or pd.isna(avg):
                raise ValueError(f"No FX rate of any kind available for {ccy}")
            rate_used.append(avg)
            rate_source.append("period_average_fallback")
            low_conf.append(True)
            warnings.append(
                f"FX GAP: {ccy} has no published period-end rate for the period. "
                f"Falling back to period-average rate ({avg}) for account {row['account_code']} "
                f"({row['account_name']}), row {row['source_row']}. This is a provisional "
                f"translation. Confirm with Treasury before the statements are finalized."
            )

    out["rate_used"] = rate_used
    out["rate_source"] = rate_source
    out["low_confidence"] = low_conf
    out["debit_usd"] = out["debit"] * out["rate_used"]
    out["credit_usd"] = out["credit"] * out["rate_used"]
    return out, warnings
