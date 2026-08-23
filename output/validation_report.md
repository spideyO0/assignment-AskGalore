# COA Mapper — Validation Report

**Run status: PASS WITH DISCLOSED EXCEPTIONS** (exit code 1)

Exit codes: 0 clean pass · 1 pass with disclosed exceptions (review/suspense/warn present, nothing lost) · 2 hard failure.

## 1. Inputs consumed

| File | Rows | SHA-256 |
|---|---|---|
| `chart_of_accounts.csv` | 72 | `093275cdd8513d91…` |
| `fx_rates.csv` | 7 | `93aca603be3c63ce…` |
| `prior_period_tb.csv` | 33 | `3b81c410569480e6…` |
| `trial_balance.csv` | 62 | `c1f121388aa85a77…` |

## 2. Mapping decisions

| Source | AUTO_APPLIED | REVIEW | SUSPENSE | |net USD| total |
|---|---|---|---|---|
| current | 58 | 0 | 1 | 142336460.20 |
| prior | 30 | 1 | 0 | 67692067.40 |

## 3. Reconciliation math

Every input row is accounted for exactly once; the dollar decomposition below is re-derived independently by the verifier from raw files.

**current**: rows 61 + 0 + 1 = 62; $142324060.20 + $0.00 + $12400.00 = $142336460.20 — no remainder, nothing dropped.

**prior**: rows 32 + 1 + 0 = 33; $67560067.40 + $132000.00 + $0.00 = $67692067.40 — no remainder, nothing dropped.

## 4. Findings

| Severity | Code | Detail |
|---|---|---|
| WARN | `DUP_ACCOUNT_CURRENCY` | current account 6310 currency USD: 2 rows with same code+currency; summed per convention but flagged as double-post signature |
| WARN | `FX_PERIOD_END_FALLBACK` | currency GBP: no period_end rate; translated at period_average fallback for accounts [1110]; provisional |
| WARN | `FX_PERIOD_END_FALLBACK` | currency GBP: no period_end rate; translated at period_average fallback for accounts [1110]; provisional |
| INFO | `COA_CHILDLESS_HEADER` | COA header 1290 Other Assets: no children mapped; informational for BS/P&L rollup hygiene |
| INFO | `COA_ROOT_LEAF` | COA account 8000 Income Tax Expense: leaf with no parent; sits outside the hierarchy |
| INFO | `COA_TBD_CATEGORY` | COA account 1150 Other Current Assets: cash-flow category is TBD; blocks cash-flow statement only |
| INFO | `COA_TBD_CATEGORY` | COA account 2170 Intercompany Payable: cash-flow category is TBD; blocks cash-flow statement only |
| INFO | `FX_UNKNOWN_RATE_TYPE` | fx_rates.csv:7 currency EUR: rate_type 'opening' not consumed by mapping policy (point-in-time balances use period_end); ignored |
| INFO | `FX_UNKNOWN_RATE_TYPE` | fx_rates.csv:8 currency GBP: rate_type 'opening' not consumed by mapping policy (point-in-time balances use period_end); ignored |

## 5. Verification checks (independent re-derivation)

| Check | Result | Detail |
|---|---|---|
| `current:row_conservation` | PASS | input_rows=62 covered=62 missing=[] extra=[] overlaps=[] |
| `current:usd_conservation` | PASS | |sum(nets)|=142336460.20 sum(|decision nets|)=142336460.20 |
| `current:decision_reproduction` | PASS | independently re-derived 59 account decisions; diverged=[] |
| `current:auto_gate_integrity` | PASS | AUTO_APPLIED=58 threshold_violations=[] |
| `current:dispositions_total` | PASS | accounts=59 every disposition valid with reasons; invalid=[] |
| `current:fx_fallbacks_flagged` | PASS | independently recomputed fallbacks=['GBP'] disclosed_in_findings=['GBP'] untranslatable_routed_to_suspense=set() |
| `prior:row_conservation` | PASS | input_rows=33 covered=33 missing=[] extra=[] overlaps=[] |
| `prior:usd_conservation` | PASS | |sum(nets)|=67692067.40 sum(|decision nets|)=67692067.40 |
| `prior:decision_reproduction` | PASS | independently re-derived 31 account decisions; diverged=[] |
| `prior:auto_gate_integrity` | PASS | AUTO_APPLIED=30 threshold_violations=[] |
| `prior:dispositions_total` | PASS | accounts=31 every disposition valid with reasons; invalid=[] |
| `prior:fx_fallbacks_flagged` | PASS | independently recomputed fallbacks=['GBP'] disclosed_in_findings=['GBP'] untranslatable_routed_to_suspense=set() |
| `artifacts:idempotent_render` | PASS | data artifacts rendered twice byte-identical=True files=['decisions.jsonl', 'mapped_tb_current.csv', 'mapped_tb_prior.csv', 'review_queue.csv', 'suspense.csv'] |

## 6. Review queue (human sign-off required)

| Source | TB account | Net USD | Proposed → COA | Conf | Runner-up | Margin | Flags |
|---|---|---|---|---|---|---|---|
| prior | 6905 Sundry Operating Expenses | 132000.00 | 6900 Other Operating Expenses | 0.8002 | 8200 (0.5127) | 0.2875 | — |

## 7. Suspense (excluded from applied mappings, never dropped)

| Source | TB account | Net USD | Reason |
|---|---|---|---|
| current | 9999 Suspense - Unmapped | 12400.00 | tier=NO_CANDIDATE confidence=0.3507 margin=0.0201 features[code_proximity=0.0000;name_similarity=0.5455;token_overlap=0.0000] |

## 8. Configuration echo

```yaml
{
  "auto_min": 0.9,
  "max_suspense_ratio": 0.5,
  "review_min": 0.6,
  "sources": [
    "current",
    "prior"
  ],
  "tie_epsilon": 0.03,
  "top_k": 3,
  "weights": {
    "balance_continuity": 0.3,
    "code_proximity": 0.1,
    "name_similarity": 0.45,
    "token_overlap": 0.15
  }
}
```
