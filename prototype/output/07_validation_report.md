# Validation Report, 2024-Q4

**Overall status: PASS WITH DISCLOSED EXCEPTIONS**


## Checks

| Check | Status | Detail |
|---|---|---|
| adjustments_accounted_for | PASS | All 10 entries dispositioned: {'ACCEPT': 7, 'QUARANTINE': 2, 'REJECT': 1}. |
| tb_balances_post_fx | FAIL | Trial balance does not balance after FX translation: debit $71,259,460.20 vs credit $71,077,000.00 (diff $182,460.20). This is a source-system break, not a rounding artifact, and it must be investigated with the ERP team before statements are considered final. Carried through to the balance sheet as a disclosed, unreconciled difference rather than plugged. |
| no_unmapped_accounts | WARN | Account(s) 9999 have no COA mapping and were excluded from the statements (net $12,400.00). Held in suspense pending a mapping decision. See the TB to COA mapper slice for how this would be triaged with a confidence score. |
| no_duplicate_tb_rows | WARN | Account(s) 6310 appear more than once for the same currency in the source TB export. Summed per the stated convention, but flagged, since this is also the signature of an accidental double-post in the ERP and should be confirmed with the source system owner. |
| fx_rates_confirmed | WARN | GBP translated using a period-average fallback rate because no period-end rate was published (net exposure $521,147.20 in functional currency). Statements are usable but this balance should be re-translated once Treasury confirms the period-end rate. |
| balance_sheet_balances | FAIL | Assets ($36,234,760.20) is not equal to Liabilities + Equity ($36,064,700.00), gap $170,060.20. Not plugged. See tb_balances_post_fx and no_unmapped_accounts checks above for the two root causes that roll up into this gap. |
| coa_hygiene | WARN | cf_category is ambiguous ('TBD') for: 1150, 2170. Does not block BS/P&L but will break the Cash Flow Statement slice. Header node(s) with no mapped children: 1290. |

## Adjustment dispositions

| ID | Status | Reason |
|---|---|---|
| JE-001 | ACCEPT | Balanced, all accounts resolve in the COA, net economic effect confirmed. |
| JE-002 | REJECT | Entry does not balance: total debits $28,500.00 vs total credits $25,000.00 (difference $3,500.00). A journal entry must balance before it can be posted. Please correct and resubmit. Source: Controller note 2024-12-28. |
| JE-003 | ACCEPT | Balanced, all accounts resolve in the COA, net economic effect confirmed. |
| JE-004 | ACCEPT | Balanced, all accounts resolve in the COA, net economic effect confirmed. |
| JE-005 | QUARANTINE | References account(s) 6315 which do not exist in the chart of accounts. The entry balances arithmetically, but we cannot post to an account that is not mapped. Routing to the COA steward to either map or add the account, or correct the entry. Source: AP team. |
| JE-006 | ACCEPT | Balanced, all accounts resolve in the COA, net economic effect confirmed. |
| JE-007 | ACCEPT | Balanced, all accounts resolve in the COA, net economic effect confirmed. |
| JE-008 | QUARANTINE | All lines net to zero across the same account(s) (2170). This entry has no net economic effect on any balance. That usually means a contra-account was mis-keyed, for example an intercompany entry that should hit the counterparty's account, rather than a genuine adjustment. Escalating to the preparer for the correct offsetting account. Source: IC reconciliation. |
| JE-009 | ACCEPT | Balanced, all accounts resolve in the COA, net economic effect confirmed. |
| JE-010 | ACCEPT | Balanced, all accounts resolve in the COA, net economic effect confirmed. |

## FX warnings

- FX GAP: GBP has no published period-end rate for the period. Falling back to period-average rate (1.264) for account 1110 (Cash and Cash Equivalents), row 2. This is a provisional translation. Confirm with Treasury before the statements are finalized.