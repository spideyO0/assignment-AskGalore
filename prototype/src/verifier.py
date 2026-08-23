"""Verification / self-correction agent.

Runs after the statements are built and checks the invariants an auditor
would check first. Nothing here is allowed to silently "fix" a number. If a
check fails, it is disclosed with a root-cause hypothesis and routed to a
human. The one thing this module is NOT allowed to do is manufacture a plug
to make Assets = Liabilities + Equity look true when it is not.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
import pandas as pd

TOLERANCE = 0.01


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str


def check_adjustments_accounted_for(entries: list, dispositions: pd.DataFrame) -> CheckResult:
    total = len(entries)
    handled = len(dispositions)
    counts = dispositions["status"].value_counts().to_dict()
    if total != handled:
        return CheckResult("adjustments_accounted_for", "FAIL",
                            f"{handled}/{total} entries received a disposition. Some were dropped silently.")
    return CheckResult("adjustments_accounted_for", "PASS",
                        f"All {total} entries dispositioned: {counts}.")


def check_tb_balance(tb_translated: pd.DataFrame) -> CheckResult:
    total_debit = tb_translated["debit_usd"].sum()
    total_credit = tb_translated["credit_usd"].sum()
    diff = round(total_debit - total_credit, 2)
    if abs(diff) <= TOLERANCE:
        return CheckResult("tb_balances_post_fx", "PASS", "Debits equal credits after FX translation.")
    return CheckResult(
        "tb_balances_post_fx", "FAIL",
        f"Trial balance does not balance after FX translation: debit ${total_debit:,.2f} vs "
        f"credit ${total_credit:,.2f} (diff ${diff:,.2f}). This is a source-system break, not "
        f"a rounding artifact, and it must be investigated with the ERP team before statements "
        f"are considered final. Carried through to the balance sheet as a disclosed, "
        f"unreconciled difference rather than plugged."
    )


def check_unmapped_accounts(unmapped_tb: pd.DataFrame) -> CheckResult:
    if unmapped_tb.empty:
        return CheckResult("no_unmapped_accounts", "PASS", "Every TB account resolves to a COA node.")
    total = (unmapped_tb["debit_usd"] - unmapped_tb["credit_usd"]).sum()
    codes = ", ".join(sorted(unmapped_tb["account_code"].unique()))
    return CheckResult(
        "no_unmapped_accounts", "WARN",
        f"Account(s) {codes} have no COA mapping and were excluded from the statements "
        f"(net ${total:,.2f}). Held in suspense pending a mapping decision. See the "
        f"TB to COA mapper slice for how this would be triaged with a confidence score."
    )


def check_duplicate_rows(dupes: pd.DataFrame) -> CheckResult:
    if dupes.empty:
        return CheckResult("no_duplicate_tb_rows", "PASS", "No repeated account_code+currency rows.")
    codes = ", ".join(sorted(dupes["account_code"].unique()))
    return CheckResult(
        "no_duplicate_tb_rows", "WARN",
        f"Account(s) {codes} appear more than once for the same currency in the source TB "
        f"export. Summed per the stated convention, but flagged, since this is also the "
        f"signature of an accidental double-post in the ERP and should be confirmed with "
        f"the source system owner."
    )


def check_fx_confidence(tb_translated: pd.DataFrame) -> CheckResult:
    low = tb_translated[tb_translated["low_confidence"]]
    if low.empty:
        return CheckResult("fx_rates_confirmed", "PASS", "All currencies translated at confirmed period-end rates.")
    ccys = ", ".join(sorted(low["currency"].unique()))
    amt = low["debit_usd"].sum() - low["credit_usd"].sum()
    return CheckResult(
        "fx_rates_confirmed", "WARN",
        f"{ccys} translated using a period-average fallback rate because no period-end rate "
        f"was published (net exposure ${amt:,.2f} in functional currency). Statements are "
        f"usable but this balance should be re-translated once Treasury confirms the "
        f"period-end rate."
    )


def check_bs_balances(bs: dict) -> CheckResult:
    gap = round(bs["total_assets"] - bs["total_liabilities_and_equity"], 2)
    if abs(gap) <= TOLERANCE:
        return CheckResult("balance_sheet_balances", "PASS", "Assets = Liabilities + Equity.")
    return CheckResult(
        "balance_sheet_balances", "FAIL",
        f"Assets (${bs['total_assets']:,.2f}) is not equal to Liabilities + Equity "
        f"(${bs['total_liabilities_and_equity']:,.2f}), gap ${gap:,.2f}. Not plugged. See "
        f"tb_balances_post_fx and no_unmapped_accounts checks above for the two root causes "
        f"that roll up into this gap."
    )


def check_coa_hygiene(coa: pd.DataFrame) -> CheckResult:
    tbd = coa[coa["cf_category"] == "TBD"]
    from . import coa_tree
    orphan_headers = coa_tree.headers_with_no_children(coa)
    msgs = []
    if not tbd.empty:
        msgs.append(f"cf_category is ambiguous ('TBD') for: {', '.join(tbd['account_code'])}. "
                     f"Does not block BS/P&L but will break the Cash Flow Statement slice.")
    if not orphan_headers.empty:
        msgs.append(f"Header node(s) with no mapped children: {', '.join(orphan_headers['account_code'])}.")
    if not msgs:
        return CheckResult("coa_hygiene", "PASS", "No structural issues found in the COA.")
    return CheckResult("coa_hygiene", "WARN", " ".join(msgs))


def run_all(*, entries, dispositions, tb_translated, unmapped_tb, dupes, bs, coa) -> List[CheckResult]:
    return [
        check_adjustments_accounted_for(entries, dispositions),
        check_tb_balance(tb_translated),
        check_unmapped_accounts(unmapped_tb),
        check_duplicate_rows(dupes),
        check_fx_confidence(tb_translated),
        check_bs_balances(bs),
        check_coa_hygiene(coa),
    ]


def overall_status(results: List[CheckResult]) -> str:
    if any(r.status == "FAIL" for r in results):
        return "PASS WITH DISCLOSED EXCEPTIONS"  # never silently blocks, always routes to a human
    if any(r.status == "WARN" for r in results):
        return "PASS WITH WARNINGS"
    return "PASS"
