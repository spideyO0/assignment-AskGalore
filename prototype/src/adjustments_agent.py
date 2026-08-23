"""Manual-adjustments validation agent.

This is the one place in the pipeline where "agent" behavior is more than a
loop of pure math. Each entry gets a disposition (ACCEPT, REJECT, or
QUARANTINE) plus a plain-English reason a finance user can act on. In this
prototype the rules are deterministic and hand-written, which is deliberate.
See architecture.md section 2 for why an LLM is used to *phrase* the
explanation and to *triage novel patterns*, not to decide whether debits
equal credits.

Disposition rules, in order:
  1. Lines do not sum to zero net (debit != credit)      -> REJECT
  2. Any referenced account is not in the COA             -> QUARANTINE
  3. All lines net to zero on the *same* account          -> QUARANTINE
     (a "circular" entry, meaning no real economic movement, likely a
     wrong contra-account rather than a genuine adjustment)
  4. Otherwise                                            -> ACCEPT
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
import pandas as pd

TOLERANCE = 0.01


@dataclass
class Disposition:
    id: str
    description: str
    status: str  # ACCEPT | REJECT | QUARANTINE
    reasons: List[str] = field(default_factory=list)
    total_debit: float = 0.0
    total_credit: float = 0.0
    accounts: List[str] = field(default_factory=list)


def evaluate_entries(entries: list, coa: pd.DataFrame) -> List[Disposition]:
    valid_accounts = set(coa["account_code"])
    results: List[Disposition] = []

    for je in entries:
        lines = je["lines"]
        total_debit = round(sum(l["debit"] for l in lines), 2)
        total_credit = round(sum(l["credit"] for l in lines), 2)
        accounts = [l["account"] for l in lines]
        d = Disposition(
            id=je["id"], description=je["description"],
            status="ACCEPT", total_debit=total_debit, total_credit=total_credit,
            accounts=accounts,
        )

        if abs(total_debit - total_credit) > TOLERANCE:
            d.status = "REJECT"
            d.reasons.append(
                f"Entry does not balance: total debits ${total_debit:,.2f} vs "
                f"total credits ${total_credit:,.2f} (difference "
                f"${abs(total_debit - total_credit):,.2f}). A journal entry must "
                f"balance before it can be posted. Please correct and resubmit. "
                f"Source: {je.get('source', 'unknown')}."
            )
            results.append(d)
            continue

        unknown = sorted({a for a in accounts if a not in valid_accounts})
        if unknown:
            d.status = "QUARANTINE"
            d.reasons.append(
                f"References account(s) {', '.join(unknown)} which do not exist in the "
                f"chart of accounts. The entry balances arithmetically, but we cannot "
                f"post to an account that is not mapped. Routing to the COA steward to "
                f"either map or add the account, or correct the entry. Source: "
                f"{je.get('source', 'unknown')}."
            )
            results.append(d)
            continue

        # Circular / self-canceling: every distinct account nets to zero across the entry.
        net_by_account = {}
        for l in lines:
            net_by_account[l["account"]] = net_by_account.get(l["account"], 0.0) + l["debit"] - l["credit"]
        if len(net_by_account) == 1 or all(abs(v) < TOLERANCE for v in net_by_account.values()):
            d.status = "QUARANTINE"
            d.reasons.append(
                f"All lines net to zero across the same account(s) "
                f"({', '.join(sorted(net_by_account))}). This entry has no net economic "
                f"effect on any balance. That usually means a contra-account was mis-keyed, "
                f"for example an intercompany entry that should hit the counterparty's "
                f"account, rather than a genuine adjustment. Escalating to the preparer for "
                f"the correct offsetting account. Source: {je.get('source', 'unknown')}."
            )
            results.append(d)
            continue

        d.reasons.append("Balanced, all accounts resolve in the COA, net economic effect confirmed.")
        results.append(d)

    return results


def to_dataframe(dispositions: List[Disposition]) -> pd.DataFrame:
    return pd.DataFrame([{
        "id": d.id,
        "description": d.description,
        "status": d.status,
        "total_debit": d.total_debit,
        "total_credit": d.total_credit,
        "accounts": "|".join(d.accounts),
        "reason": " ".join(d.reasons),
    } for d in dispositions])
