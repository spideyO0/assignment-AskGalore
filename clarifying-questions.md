# Clarifying questions

The brief allows up to three questions before starting. These are mine. Each
is a question about **accounting policy** — a fact about the business, not a
fact about the data — which is why no amount of engineering resolves it.

None of them blocked the work. I made an explicit assumption for each,
documented below, and isolated it to a specific line item so a reviewer can
override one without re-running anything else.

Deliberately **not** on this list: every seeded data defect (missing GBP
period-end rate, orphan account `9999`, unbalanced JE-002, circular JE-008,
renamed `6905`, duplicate `6310`, `TBD` cash-flow categories). Those are not
questions — they are the work, and they are handled unattended and disclosed.
See [`architecture.md`](architecture.md) §4.

---

### 1. Where does unrealised FX revaluation land — P&L or OCI?

**Why it matters.** `manual_adjustments.json` JE-003 books it to
`7310 FX Gain/Loss - Unrealized` (P&L), but the COA carries a separate
`3310 FX Translation Reserve` (OCI/equity) that already holds a balance in
the TB. Those are two different accounting policies —
functional-currency remeasurement versus translation of a net investment —
and they produce materially different net income.

**Assumption made.** Followed the journal entry as instructed (P&L). Did not
re-route it to OCI. Reclassifying a named entry against its own explicit
instruction is a larger liability than following it, and the entry is
traceable either way.

**Who answers it.** The controller, before the next close.

---

### 2. Is the trial balance pre- or post-intercompany elimination?

**Why it matters.** The TB carries a live `2170 Intercompany Payable`
balance and JE-008 attempts an IC settlement against it. If this book is
already consolidated, that balance should be eliminated; if it is a single
entity's book, it is presented gross.

**Assumption made.** Treated as a **single-entity book, no consolidation**.
IC balances presented gross. This is recorded as a scope boundary rather
than resolved by inferring a counterparty entity that does not exist in the
provided data.

**Who answers it.** Whoever owns the consolidation structure. It changes the
architecture, not just a number — real consolidation needs a cross-entity IC
matching engine, which is out of scope here.

---

### 3. What is the correct counterparty account for JE-008?

**Why it matters.** Both legs of JE-008 hit `2170`, so the entry nets to
zero and moves nothing. Either the entry is a mistake, or a contra-account
was mis-keyed and $320,000 is meant to move somewhere specific.

**Assumption made.** Did not guess. The entry is **quarantined** with the
hypothesis stated (wrong contra-account) and routed to the preparer.
Inventing a plausible bank or sub-ledger account would silently move
$320,000 with no audit basis — a worse failure than an unposted, flagged
entry.

**Who answers it.** The preparer who raised the IC reconciliation.

---

## A fourth thing I assumed rather than asked

**Is this TB closed for the period, or still open (interim)?** The presence
of `8100`/`8200` tax activity and a JE-driven bonus accrual suggests interim
and unclosed. I treated it as unclosed and present current-period net income
as an explicit *unappropriated* equity line rather than assuming it is
already rolled into `3200 Retained Earnings` — which would double-count it
if wrong. This is lower-stakes than the three above because the presentation
makes the assumption visible on the face of the statement.
