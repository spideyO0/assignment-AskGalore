# Approach

How this was actually built: the decisions that mattered, in the order they were
made, and what each one cost or bought.

`architecture.md` describes the design. This describes the *process* — including
the parts that went wrong.

---

## 1. Read the data before designing anything

The brief says the mock data is intentionally messy and that it lists fewer
defects than it seeds. So the first work was not architecture, it was an audit:
compute the actual FX-translated debit and credit totals, diff the TB account set
against the COA, walk the adjustment entries against their own arithmetic.

That produced the exact figures the design then had to accommodate:

- the TB break is **$182,460.20** — an order of magnitude too large to be FX
  rounding, so "tolerance" was never going to be the answer
- `9999` is in the TB and not in the COA, carrying **$12,400.00**
- GBP has a `period_average` rate and no `period_end` rate
- `6310` appears twice for the same currency
- prior-period `6905` looks like current `6900` under a different name

Two defects the brief never mentions surfaced here and shaped the design more
than the listed ones did:

- **`8000 Income Tax Expense` is a leaf with no parent.** Any rollup that walks
  parent links from a root silently omits it. This is the reason the design
  treats "is every account reachable" as a checkable property rather than an
  assumption.
- **`fx_rates.csv` carries an `opening` rate type** that the brief's schema
  description does not mention. An input can contain data your policy has no
  place for, and the honest response is to say you ignored it, not to quietly
  drop it.

Doing this first meant the architecture was written against real defects rather
than imagined ones. Nothing in the design is speculative.

---

## 2. Decompose before choosing a topology

"Generate the financial statements" is not one problem. Writing out the
sub-problems first made the agent question answer itself:

| Sub-problem | Reliability need | Consequence |
|---|---|---|
| Parse and validate source files | never silently accept garbage | deterministic |
| Map TB accounts to COA nodes | judgment, but must never guess silently | **the interesting one** |
| FX translation | exactly correct or explicitly flagged | deterministic |
| Validate manual adjustments | interpret memos, explain rejections | rules + language |
| Roll into statements | arithmetic | deterministic |
| Verify and emit an audit trail | must not rubber-stamp itself | independent re-derivation |

Four of six are arithmetic. That is the whole argument against a swarm: most of
this problem by line count *and* by dollar value at risk has one correct answer,
and an agent that free-reasons over it makes that answer non-reproducible.

So the topology is a deterministic orchestrator calling narrow stages with typed
contracts, and only two stages are candidates for a model at all.

---

## 3. Pick the slice where the design question is live

Of the four slices offered, three would have been a demonstration of plumbing:

- statement generation from a resolved ledger is group-sum-sign-convert
- adjustment validation is a rule engine with good error messages
- reconciliation is genuinely hard but open-ended enough to be unfinishable in
  the time

Mapping is the one where a system either guesses and is quietly wrong, or scores
its evidence, gates on a threshold, and escalates what it cannot justify. It is
also where a mistake is invisible until an auditor finds it, which is exactly the
failure mode the brief cares about.

---

## 4. Build the judgment stage without a model, on purpose

The starting assumption was that the mapper would need an LLM for the fuzzy
cases. It did not, and finding that out changed the architecture's central claim.

The seeded rename — prior `6905 Sundry Operating Expenses` versus current
`6900 Other Operating Expenses` — is caught by a weighted feature vector:

| Feature | Weight | Contribution on `6905 → 6900` |
|---|---|---|
| `name_similarity` | 0.45 | 0.8163 |
| `balance_continuity` | 0.30 | 0.9429 |
| `token_overlap` | 0.15 | 0.5000 |
| `code_proximity` | 0.10 | 0.7500 |

Composite **0.8002** — below the 0.90 auto threshold, above the 0.60 review
floor, so it queues for a human. That is the correct outcome, and it is
reproducible byte-for-byte, which a model's answer would not be.

`balance_continuity` is what does the real work: it compares the account's
balance against the *other period's* balance for each candidate. A rename keeps
its balance; a coincidence usually does not.

So the honest boundary is not "code for arithmetic, model for judgment". It is:
**use a model only where the evidence is unstructured text no feature can
score.** `semantic.py` is that slot, built and tested but shipped disabled,
entering the same weighted vector under the same gate — a feature, never a
verdict.

---

## 5. Make "nothing is lost" a checkable property, not a promise

Every design document claims nothing is silently dropped. The difference here is
that the claim is enforced:

- **row conservation** — every input row is claimed by exactly one decision, no
  missing, no extra, no overlap
- **USD conservation** — Σ|net| decomposes exactly across applied / review /
  suspense with no remainder
- **decision reproduction** — an independent re-run of the gate diverges on zero
  accounts
- **auto-gate integrity** — nothing auto-applied below threshold or carrying a
  veto
- **idempotent render** — artifacts rendered twice are byte-identical

The verifier reloads the raw inputs from disk and recomputes rather than
re-reading the pipeline's conclusions. That distinction earned its keep: when a
bug zeroed out a partially-translatable account, the conservation check is what
caught it.

---

## 6. Treat the exit code as an API

Three codes, and the discipline is that a failure can never masquerade as a
reviewable run:

| Code | Meaning |
|---|---|
| `0` | clean |
| `1` | disclosed exceptions — nothing lost, humans have work to do |
| `2` | hard failure — an ERROR finding, a failed check, or a run that could not complete |

This sounds like bookkeeping until you wire CI as "fail on 2, review on 1" and
discover an unreadable input was exiting `1`.

---

## 7. Find bugs by attacking the code, not by re-reading it

The suite that came out of building the happy path passed. Four techniques found
real defects anyway, and all four are now permanent:

**Independent re-derivation.** An auditor script that reads `inputs/` and
`output/` and reimplements the documented formulas *without importing the
package*. 329 checks: tier assignment, every feature value, composite scores,
runner-up rankings, conservation, input hashes. This is how the audit trail's
reproducibility was tested rather than assumed.

**Adversarial input probing.** 20 malformed-input scenarios — missing file, empty
file, renamed column, non-numeric amount, zero and negative FX rates, duplicate
COA codes, a COA with no leaves, a parent cycle, BOM, CRLF, blank lines,
whitespace padding. Five deviated from the documented contract. All five are
fixed and each has a regression test.

**Property-based testing.** Hypothesis generating trial balances found a rounding
inconsistency no example test would have: `595.00 × 1.095 = 651.525`, quantized
half-up in one place and banker's-rounded in another, disagreeing by a cent.

**Turning the linters on.** ruff and mypy on code that already passed its tests
found three genuine bugs, the worst being that the pipeline built its thresholds
as `Decimal` and the verifier built the same thresholds as `float`. Since float
`0.90` is `0.9000000000000000222`, an account scoring exactly `0.9000` would
auto-apply in one and go to review in the other — a spurious reproduction failure
that would exit `2` on a correct mapping. Nothing on this dataset scores exactly
0.9000, which is the only reason it never fired.

The throughline: **every one of these found something the existing tests could
not, because they attack the code from outside its own assumptions.**

---

## 8. Fix causes, not symptoms

Two examples where the first visible problem was not the real one.

**The suspense row that said $0.00.** An account with one untranslatable currency
row reported `$0.00` in suspense while holding `$1,424,960.20` in rows that
translated fine. The obvious fix is to populate the amount. The actual cause was
two levels down: the pipeline emitted a decision for the translatable aggregate
*and* a synthesized stub for the same account, so it was dispositioned twice and
the zero stub won. Fixing the amount alone would have left the double-count.

Chasing that exposed a second defect: the verifier overwrote the pipeline's
claimed decisions with its own re-derivation before summing, so a wrong amount in
the artifact could not fail the conservation check that existed to catch it.

**The score that would not reconcile.** `9999` published
`name_similarity: 0.5455` and `confidence: 0.3506`, but recomputing from the
published vector gives `0.3507`. Cause: confidence was computed from
full-precision floats while the feature vector was rounded separately for
display. The fix is to round first and score from what was published — so an
auditor recomputing by hand lands on the same digit. Patching the displayed
number would have hidden the actual problem, which is that the audit trail did
not reconcile with itself.

---

## 9. Two front doors, one pipeline

The CLI came first because it is the thing that has to be scriptable and
CI-friendly. The UI was added as a second shell over the *same* `run(config)` —
not a reimplementation, not a service with its own logic:

- the API is standard-library only, so the two-dependency claim survives
- it is stateless: uploads go to a temp directory that is destroyed per request
- a test asserts the API's seven artifacts are **byte-identical** to the CLI's

That last point is the one that matters. A UI that computes slightly different
numbers than the batch job is worse than no UI.

The UI itself is deliberately read-only. It makes a run *inspectable* — click an
account, see the feature vector, the weights, the composite those exact numbers
produce, the reasons, the source rows, the FX rate applied to each. It does not
let you edit a mapping, because persisting human overrides is a real feature with
provenance and idempotency requirements, and a half-built version of it would be
worse than an honest gap.

---

## 10. What was deliberately not built

- **Statement generation, adjustments, reconciliation** — the other three slices.
  Designed in `architecture.md`, not coded. The brief asks for one slice done
  properly.
- **Persisted human overrides.** `review_queue.csv` is where `6905 → 6900` waits,
  and nothing consumes it. This is the single biggest gap and `reflection.md`
  says so.
- **A live model provider.** The slot, the gate integration and the reproducible
  cache exist; no provider ships, because this dataset does not need one and
  wiring a network call into a pipeline whose selling point is determinism needs
  the strict-mode cache to be the default, not an afterthought.
- **Candidate blocking.** The matcher is O(n·m). Fine at 90 accounts, wrong at
  5,000. Named in `reflection.md` rather than half-solved.

Each of these is a place where building a shallow version would have made the
system look more complete and be less trustworthy.
