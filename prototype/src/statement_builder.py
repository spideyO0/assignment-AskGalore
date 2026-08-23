"""Builds P&L and Balance Sheet from the posted ledger and COA hierarchy.

Every number here is pure arithmetic over already-validated inputs, and this
file deliberately contains no judgment calls. See architecture.md for why
that is the point. By the time we get here, ambiguity has already been
resolved (accounts mapped, adjustments dispositioned, FX translated) or
explicitly quarantined out.

Sign convention: each statement section (Revenue, COGS, OpEx, Assets,
Liabilities, Equity, and so on) has one polarity, not each account. A
"contra" account (for example 4200 Sales Returns is debit-balance inside a
credit-normal Revenue section, and 1211 Accumulated Depreciation is
credit-balance inside a debit-normal Assets section) is computed AGAINST the
section's polarity, so it naturally nets negative and reduces the section
total, the way a real financial statement presents contra-accounts. Rolling
up each account against its own individual normal_balance instead (an
earlier version of this file did that) silently double-counts contra
accounts as additive and blows up the balance sheet, worth calling out
because it is an easy, quiet mistake.
"""
from __future__ import annotations
import pandas as pd
from . import coa_tree

PL_REVENUE = ["4100", "4110", "4200", "4300"]
PL_COGS = ["5100", "5110", "5120"]
PL_OPEX = ["6100", "6110", "6120", "6200", "6210", "6220", "6300", "6310",
           "6315",  # quarantined account, only appears if a future run accepts it
           "6400", "6410", "6500", "6510", "6600", "6900"]
PL_NONOP_INCOME = ["7100"]
PL_NONOP_EXPENSE = ["7200", "7300", "7310", "7400"]
PL_TAX = ["8100", "8200"]

BS_ASSETS = ["1110", "1120", "1121", "1130", "1131", "1140", "1150",
             "1210", "1211", "1220", "1221", "1230", "1240", "1250"]
BS_LIABILITIES = ["2110", "2120", "2130", "2140", "2150", "2160", "2170",
                   "2210", "2220", "2230", "2240"]
BS_EQUITY = ["3100", "3110", "3200", "3310", "3400"]

# Section polarity: "Debit" means balance = debit_usd - credit_usd. "Credit" is the reverse.
SECTION_POLARITY = {
    "revenue": "Credit", "cogs": "Debit", "opex": "Debit",
    "nonop_income": "Credit", "nonop_expense": "Debit", "tax": "Debit",
    "assets": "Debit", "liabilities": "Credit", "equity": "Credit",
}


def account_lineage(ledger: pd.DataFrame) -> dict:
    lineage = {}
    for _, row in ledger.iterrows():
        lineage[row["account_code"]] = {
            "debit_usd": row["debit_usd"], "credit_usd": row["credit_usd"],
            "source_rows": row.get("source_rows", []),
            "je_refs": row.get("je_refs", []),
            "low_confidence": row.get("low_confidence", False),
        }
    return lineage


def _line(coa: pd.DataFrame, code: str, ledger_by_code: dict, polarity: str) -> dict:
    name_series = coa.loc[coa["account_code"] == code, "account_name"]
    name = name_series.iloc[0] if len(name_series) else code
    vals = ledger_by_code.get(code, {"debit_usd": 0.0, "credit_usd": 0.0})
    amount = vals["debit_usd"] - vals["credit_usd"] if polarity == "Debit" else vals["credit_usd"] - vals["debit_usd"]
    return {"account_code": code, "account_name": name, "amount": round(amount, 2)}


def _section(coa, ledger_by_code, codes, key):
    return [_line(coa, c, ledger_by_code, SECTION_POLARITY[key]) for c in codes if c in ledger_by_code or True]


def build_pl(ledger: pd.DataFrame, coa: pd.DataFrame) -> dict:
    ledger_by_code = ledger.set_index("account_code").to_dict(orient="index")
    lineage = account_lineage(ledger)

    revenue_lines = _section(coa, ledger_by_code, PL_REVENUE, "revenue")
    total_revenue = round(sum(l["amount"] for l in revenue_lines), 2)

    cogs_lines = _section(coa, ledger_by_code, PL_COGS, "cogs")
    total_cogs = round(sum(l["amount"] for l in cogs_lines), 2)
    gross_profit = round(total_revenue - total_cogs, 2)

    opex_lines = [l for l in _section(coa, ledger_by_code, PL_OPEX, "opex") if l["account_code"] in ledger_by_code]
    total_opex = round(sum(l["amount"] for l in opex_lines), 2)
    operating_income = round(gross_profit - total_opex, 2)

    nonop_income_lines = _section(coa, ledger_by_code, PL_NONOP_INCOME, "nonop_income")
    nonop_expense_lines = _section(coa, ledger_by_code, PL_NONOP_EXPENSE, "nonop_expense")
    total_nonop = round(
        sum(l["amount"] for l in nonop_income_lines) - sum(l["amount"] for l in nonop_expense_lines), 2
    )
    income_before_tax = round(operating_income + total_nonop, 2)

    tax_lines = _section(coa, ledger_by_code, PL_TAX, "tax")
    total_tax = round(sum(l["amount"] for l in tax_lines), 2)
    net_income = round(income_before_tax - total_tax, 2)

    return {
        "period": "2024-Q4",
        "revenue": revenue_lines, "total_revenue": total_revenue,
        "cogs": cogs_lines, "total_cogs": total_cogs,
        "gross_profit": gross_profit,
        "operating_expenses": opex_lines, "total_operating_expenses": total_opex,
        "operating_income": operating_income,
        "non_operating_income": nonop_income_lines,
        "non_operating_expense": nonop_expense_lines,
        "total_non_operating": total_nonop,
        "income_before_tax": income_before_tax,
        "tax_expense": tax_lines, "total_tax_expense": total_tax,
        "net_income": net_income,
    }, lineage


def build_bs(ledger: pd.DataFrame, coa: pd.DataFrame, net_income: float) -> dict:
    ledger_by_code = ledger.set_index("account_code").to_dict(orient="index")
    lineage = account_lineage(ledger)

    asset_lines = _section(coa, ledger_by_code, BS_ASSETS, "assets")
    total_assets = round(sum(l["amount"] for l in asset_lines), 2)

    liab_lines = _section(coa, ledger_by_code, BS_LIABILITIES, "liabilities")
    total_liabilities = round(sum(l["amount"] for l in liab_lines), 2)

    equity_lines = _section(coa, ledger_by_code, BS_EQUITY, "equity")
    equity_lines.append({
        "account_code": "NI-Q4", "account_name": "Current Period Net Income (unappropriated)",
        "amount": round(net_income, 2),
    })
    total_equity = round(sum(l["amount"] for l in equity_lines), 2)

    return {
        "period_end": "2024-Q4",
        "assets": asset_lines, "total_assets": total_assets,
        "liabilities": liab_lines, "total_liabilities": total_liabilities,
        "equity": equity_lines, "total_equity": total_equity,
        "total_liabilities_and_equity": round(total_liabilities + total_equity, 2),
        "balances": total_assets == round(total_liabilities + total_equity, 2),
    }, lineage
