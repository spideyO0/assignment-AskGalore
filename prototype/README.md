# Prototype: Statement Generator (P&L + Balance Sheet) with a Verification Agent

Implements the slice from `AI_Agentic_Engineer_Assignment.pdf` §4.2:
> "Statement generator for P&L + Balance Sheet with a verification agent
> that catches its own errors before output."

It also folds in the adjacent **manual adjustments agent** slice, because a
statement generator that ignores the 10 unposted journal entries in
`manual_adjustments.json` is not generating real statements. See
`architecture.md` at the repo root for why these two are one pipeline, not
two competing slices.

## What it does

Reads `inputs/trial_balance.csv`, `inputs/chart_of_accounts.csv`,
`inputs/fx_rates.csv`, and `inputs/manual_adjustments.json` **unmodified**,
with no pre-cleaning, and produces:

1. FX-translated trial balance, with every provisional or fallback rate
   flagged
2. A disposition (ACCEPT, REJECT, or QUARANTINE, plus a plain-English
   reason) for every one of the 10 manual adjustments
3. A posted general ledger (TB plus accepted adjustments only)
4. Profit & Loss and Balance Sheet, in both JSON and Markdown
5. A validation report from an independent Verifier stage, every check,
   pass or fail, with numbers, not a rubber stamp
6. A full audit trail, so every statement line traces back to TB source
   rows and/or journal entry ids

## Run it

Requires Python 3.10 or later and `pandas`.

```bash
cd prototype
pip install pandas
python -m src.main
```

Output is written to `prototype/output/`. Re-running overwrites it, and the
pipeline is deterministic given the same three input files, so the same
inputs always produce byte-identical statements.

## Output files

| File | What it is |
|---|---|
| `01_fx_translated_trial_balance.csv` | Every TB row, rate used, rate source, and confidence flag |
| `02_unmapped_suspense_rows.csv` | TB rows with no COA match (held out, not dropped) |
| `03_adjustments_disposition.csv` | All 10 JEs with status and reason |
| `04_posted_general_ledger.csv` | One row per account: balances plus full lineage (source TB rows, JE refs) |
| `05_profit_and_loss.{json,md}` | P&L |
| `06_balance_sheet.{json,md}` | Balance Sheet |
| `07_validation_report.md` | Every verifier check plus overall status |
| `08_audit_trail.json` | Line-level lineage for every P&L/BS line |

## On this dataset, expect the run to report `PASS WITH DISCLOSED EXCEPTIONS`

That is correct behavior, not a bug. The input data has a genuine,
unexplained trial-balance break and a missing GBP period-end FX rate. The
pipeline surfaces both with exact dollar amounts rather than hiding them
behind a forced balance. See `07_validation_report.md` for the full
reconciliation. The Balance Sheet gap of $170,060.20 is shown to decompose
exactly into the $182,460.20 TB break net of the $12,400.00 excluded
suspense account.

## Code layout

```
src/
  io_loaders.py         raw file parsing, no interpretation
  fx_translation.py     currency to USD, with disclosed fallback policy
  adjustments_agent.py  ACCEPT/REJECT/QUARANTINE rules plus plain-English reasons
  ledger.py             TB plus accepted adjustments to posted ledger, with lineage
  coa_tree.py           chart-of-accounts hierarchy helpers
  statement_builder.py  pure arithmetic: ledger to P&L / Balance Sheet
  verifier.py           independent post-hoc checks that never plug a gap
  main.py               orchestrates the pipeline, writes /output
```

Each module is small and independently testable, deliberately, since the
architecture document's core claim is that most of this problem is
deterministic code with two narrow judgment points, not one LLM call over
the whole TB.
