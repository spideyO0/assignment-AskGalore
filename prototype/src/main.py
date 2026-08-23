"""Orchestrates the full pipeline and writes every artifact under /output.

Pipeline stages (mirrors architecture.md's agent topology):
  1. Load                     (io_loaders)
  2. FX-translate the TB      (fx_translation)      -> disclosed low-confidence rows
  3. Split mapped/unmapped    (ledger)               -> suspense held out, not dropped
  4. Adjustments agent        (adjustments_agent)    -> ACCEPT / REJECT / QUARANTINE plus reasons
  5. Post accepted adjustments onto the ledger        (ledger)
  6. Build P&L, then Balance Sheet (needs net income) (statement_builder)
  7. Verifier runs invariant checks, never plugs      (verifier)
  8. Write every artifact plus a full audit trail
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

from . import io_loaders, fx_translation, ledger as ledger_mod, adjustments_agent, statement_builder, verifier

OUT = Path(__file__).resolve().parents[1] / "output"


def money(x):
    return round(float(x), 2)


def main():
    OUT.mkdir(exist_ok=True)

    coa = io_loaders.load_coa()
    tb = io_loaders.load_trial_balance()
    fx = io_loaders.load_fx_rates()
    adj = io_loaders.load_adjustments()

    # 2. FX translate
    tb_translated, fx_warnings = fx_translation.translate_tb(tb, fx)
    tb_translated.to_csv(OUT / "01_fx_translated_trial_balance.csv", index=False)

    # 3. Split mapped / unmapped (suspense)
    mapped_tb, unmapped_tb = ledger_mod.split_mapped_unmapped(tb_translated, coa)
    dupes = ledger_mod.detect_duplicate_rows(tb)
    unmapped_tb.to_csv(OUT / "02_unmapped_suspense_rows.csv", index=False)

    tb_ledger = ledger_mod.build_tb_ledger(mapped_tb)

    # 4. Adjustments agent
    dispositions = adjustments_agent.evaluate_entries(adj["entries"], coa)
    disp_df = adjustments_agent.to_dataframe(dispositions)
    disp_df.to_csv(OUT / "03_adjustments_disposition.csv", index=False)
    accepted_ids = {d.id for d in dispositions if d.status == "ACCEPT"}

    # 5. Post accepted adjustments
    posted_ledger = ledger_mod.apply_adjustments(tb_ledger, adj["entries"], accepted_ids)
    posted_ledger.to_csv(OUT / "04_posted_general_ledger.csv", index=False)

    # 6. Statements
    pl, pl_lineage = statement_builder.build_pl(posted_ledger, coa)
    bs, bs_lineage = statement_builder.build_bs(posted_ledger, coa, pl["net_income"])

    with open(OUT / "05_profit_and_loss.json", "w") as f:
        json.dump(pl, f, indent=2)
    with open(OUT / "06_balance_sheet.json", "w") as f:
        json.dump(bs, f, indent=2)

    # 7. Verification
    results = verifier.run_all(
        entries=adj["entries"], dispositions=disp_df, tb_translated=tb_translated,
        unmapped_tb=unmapped_tb, dupes=dupes, bs=bs, coa=coa,
    )
    status = verifier.overall_status(results)

    # 8. Human-readable statements + validation report + audit trail
    write_pl_md(pl)
    write_bs_md(bs)
    write_validation_report(results, status, fx_warnings, disp_df)
    write_audit_trail(pl_lineage, bs_lineage, disp_df)

    print(f"Pipeline complete. Overall status: {status}")
    print(f"Artifacts written to {OUT}")


def write_pl_md(pl: dict):
    lines = ["# Profit and Loss, 2024-Q4\n"]
    def section(title, items, total_label, total):
        lines.append(f"\n## {title}\n")
        lines.append("| Account | Name | Amount (USD) |\n|---|---|---:|")
        for it in items:
            lines.append(f"| {it['account_code']} | {it['account_name']} | {it['amount']:,.2f} |")
        lines.append(f"| | **{total_label}** | **{total:,.2f}** |")
    section("Revenue", pl["revenue"], "Total Revenue", pl["total_revenue"])
    section("Cost of Goods Sold", pl["cogs"], "Total COGS", pl["total_cogs"])
    lines.append(f"\n**Gross Profit: {pl['gross_profit']:,.2f}**\n")
    section("Operating Expenses", pl["operating_expenses"], "Total OpEx", pl["total_operating_expenses"])
    lines.append(f"\n**Operating Income: {pl['operating_income']:,.2f}**\n")
    section("Non-Operating Income", pl["non_operating_income"], "Total Non-Op Income",
             sum(i["amount"] for i in pl["non_operating_income"]))
    section("Non-Operating Expense", pl["non_operating_expense"], "Total Non-Op Expense",
             sum(i["amount"] for i in pl["non_operating_expense"]))
    lines.append(f"\n**Income Before Tax: {pl['income_before_tax']:,.2f}**\n")
    section("Income Tax Expense", pl["tax_expense"], "Total Tax", pl["total_tax_expense"])
    lines.append(f"\n## Net Income: {pl['net_income']:,.2f}\n")
    (OUT / "05_profit_and_loss.md").write_text("\n".join(lines), encoding="utf-8")


def write_bs_md(bs: dict):
    lines = ["# Balance Sheet, as of 2024-Q4 period end\n"]
    def section(title, items, total_label, total):
        lines.append(f"\n## {title}\n")
        lines.append("| Account | Name | Amount (USD) |\n|---|---|---:|")
        for it in items:
            lines.append(f"| {it['account_code']} | {it['account_name']} | {it['amount']:,.2f} |")
        lines.append(f"| | **{total_label}** | **{total:,.2f}** |")
    section("Assets", bs["assets"], "Total Assets", bs["total_assets"])
    section("Liabilities", bs["liabilities"], "Total Liabilities", bs["total_liabilities"])
    section("Equity", bs["equity"], "Total Equity", bs["total_equity"])
    lines.append(f"\n**Total Liabilities + Equity: {bs['total_liabilities_and_equity']:,.2f}**\n")
    lines.append(f"\n**Balances: {bs['balances']}**\n")
    if not bs["balances"]:
        gap = bs["total_assets"] - bs["total_liabilities_and_equity"]
        lines.append(f"\n> Warning: unreconciled difference of {gap:,.2f}. See validation_report.md for root cause. "
                      f"Not plugged. Disclosed for investigation.\n")
    (OUT / "06_balance_sheet.md").write_text("\n".join(lines), encoding="utf-8")


def write_validation_report(results, status, fx_warnings, disp_df):
    lines = [f"# Validation Report, 2024-Q4\n\n**Overall status: {status}**\n"]
    lines.append("\n## Checks\n")
    lines.append("| Check | Status | Detail |\n|---|---|---|")
    for r in results:
        lines.append(f"| {r.name} | {r.status} | {r.detail} |")
    lines.append("\n## Adjustment dispositions\n")
    lines.append("| ID | Status | Reason |\n|---|---|---|")
    for _, row in disp_df.iterrows():
        lines.append(f"| {row['id']} | {row['status']} | {row['reason']} |")
    if fx_warnings:
        lines.append("\n## FX warnings\n")
        for w in fx_warnings:
            lines.append(f"- {w}")
    (OUT / "07_validation_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_audit_trail(pl_lineage, bs_lineage, disp_df):
    trail = {
        "pl_line_lineage": {k: {**v, "je_refs": list(v.get("je_refs", []))} for k, v in pl_lineage.items()},
        "bs_line_lineage": {k: {**v, "je_refs": list(v.get("je_refs", []))} for k, v in bs_lineage.items()},
        "adjustment_dispositions": disp_df.to_dict(orient="records"),
    }
    with open(OUT / "08_audit_trail.json", "w") as f:
        json.dump(trail, f, indent=2, default=str)


if __name__ == "__main__":
    main()
