# Reflection

*Design is in [`architecture.md`](architecture.md); build process and the
bug-hunting techniques are in [`approach.md`](approach.md). This is the
look-back the brief asks for.*

## What I would build differently with 3 months instead of 8 hours

The mapper I built is deterministic on purpose, and I would keep it that
way. What I would add is the layer above it: **the human-in-the-loop is
currently a CSV, not a loop.** `review_queue.csv` is where the `6905 → 6900`
rename waits, and nothing consumes it. Three months buys the closing of that
loop — a reviewer resolves an item, the decision is persisted as a mapping
override with an author and timestamp, and the next run applies it at
confidence 1.0 with provenance "human, not model". That is what makes
idempotency real rather than theoretical: same inputs *plus the same human
decisions* produce byte-identical output, and a re-run after a resolution
produces a clean, reviewable diff against the prior run rather than a fresh
wall of text.

The LLM I deliberately left out now has a **slot** rather than a plan:
`semantic.py` accepts a provider whose score enters the same weighted vector,
passes the same threshold gate, faces the same normal-balance veto, and lands
in `decisions.jsonl` like any other feature. It ships with no provider
configured, so the feature is never emitted and the artifacts are identical to
a build without it. What three months buys is the provider itself, plus the
calibration to justify its weight — I picked 0.25 by judgment, which is exactly
the kind of number that should come from measured outcomes.

The place it earns its keep is where no feature can score: `9999 Suspense -
Unmapped` has no signal in its name, its code, or its balance history, and
correctly scores 0.3507. If the COA carried prose descriptions, an embedding
similarity would have something to say there.

Then the rest of the pipeline: the adjustments agent, the statement builder,
and the two statements I did not attempt. Cash Flow stays blocked until
`cf_category` is resolved for `1150` and `2170`, which is a data question,
not an engineering one.

## Where this prototype breaks at scale

**The matcher is O(n·m) with no blocking.** Every unmatched TB account is
scored against every COA leaf. At 80 accounts that is free; at 5,000
accounts against a 20,000-node COA it is 100M rapidfuzz calls per run. The
fix is standard and I did not build it: block candidates on leading code
digits and normalised-token inverted index first, score only the surviving
few dozen.

**Confidence thresholds are per-entity, but not per-account-class.**
`config/entities/<name>.yaml` now layers thresholds and weights over the base
config, which fixes the worst version of this: one chart's tolerances no longer
govern another's. It does not fix the real problem. Within a chart, `auto_min =
0.90` is still one number, and the tolerable false-auto-map rate for a cash
account is not the rate for a miscellaneous expense account. At thousands of
accounts that single number either floods the review queue or auto-applies
things it should not. The values are also still picked by me rather than
calibrated against outcomes, which is the part no amount of config structure
solves.

**`balance_continuity` is a two-period feature and does not survive
multi-entity consolidation.** It compares an account's balance against the
same account in the other period, which is what catches the rename. Across
entities the same account code carries different balances for legitimate
reasons, so the feature that is my strongest signal here becomes noise —
worse than useless, because it is weighted 0.30.

**Intercompany elimination is absent entirely.** JE-008 is flagged as
suspicious *within one entity's book*. Real consolidation needs a
cross-entity IC matching engine dealing with asymmetric IC balances and
elimination entries that themselves need an audit trail. That is a different
and harder problem than anything in this slice.

**`decisions.jsonl` grows linearly and is append-only per run.** Fine at 90
accounts. At thousands of accounts across dozens of entities and a daily
close cadence, the audit trail needs to be queryable storage with retention
policy, not a file rewritten each run.

## How I used AI tools

I used Claude (Claude Code) to read the assignment PDF, audit the inputs for
seeded and unseeded defects, and write the pipeline iteratively.

**Where it helped most:** the mechanical audit. Computing the actual
FX-translated debit and credit totals to pin the break at exactly
$182,460.20 rather than eyeballing the CSVs, confirming GBP has no
period-end row, finding that `8000` is a leaf with no parent. Also
structuring a multi-stage pipeline so each stage has a narrow contract, and
drafting the plain-English reason strings — which is exactly the boundary
`architecture.md` argues an LLM belongs at.

**Where it led me wrong, concretely.** The mapper passed its own test suite.
That suite was written alongside the code, by the same process, and it
inherited the code's assumptions — so it proved very little. Four things that
attack the code from outside those assumptions each found something it could
not: an independent re-derivation script that reimplements the documented
formulas without importing the package; twenty malformed-input probes;
property-based generation; and simply turning ruff and mypy on.

The worst of what they found is worth stating because a model wrote it and a
human review would plausibly have passed it — it is the concrete answer to
"where did AI lead you wrong". The pipeline built its gate thresholds as
`Decimal`; the verifier built the same thresholds as `float`.
Since float `0.90` is `0.9000000000000000222`, an account scoring exactly
`0.9000` would auto-apply in the pipeline and go to review in the verifier — a
spurious reproduction failure that exits `2` on a correct mapping. Nothing in
this dataset scores exactly 0.9000, which is the only reason it never fired.
Both code paths read perfectly well; only the type checker saw it.

The generalisation I would carry forward: **generated code fails at the seams
between components that were written at different moments**, not usually inside
a single function. Each half reads correctly on its own; the disagreement only
exists between them. This is also why the verifier reloads the raw inputs and
re-derives rather than re-reading the pipeline's conclusions — an independently
derived second check against known numbers is the only thing that catches a
plausible wrong answer. Confirming the code ran without an exception confirms
nothing.

**What I did not delegate:** the threshold values, the feature weights, the
decision to veto on normal-balance conflict, and the choice of what goes to
suspense versus review. Those are policy, and a model has no basis for them.

## One thing I think this problem statement underestimates

Detecting the seeded defects is not the hard part. A rule engine finds every
one of them in milliseconds, and mine does.

The hard part is **what to do when two defects interact and the combination
is not independently diagnosable.** The balance-sheet gap in this dataset,
$170,060.20, is fully explained because it happens to decompose cleanly into
two separately-detected causes — the $182,460.20 TB break and the $12,400.00
suspense exclusion — that net to exactly the observed number. That is a
property of *this dataset*, not something the system can rely on. At real
scale a $170K gap is eleven small overlapping causes, several of which
partially offset each other, and "explain every delta line by line" becomes
a search over a combinatorial space rather than a subtraction.

That is where I would expect an LLM to genuinely earn its place —
generating and ranking plausible root-cause hypotheses over that space — and
also where I would trust it least without a human checking each proposed
explanation against the actual source rows. A confident, wrong explanation
for a reconciliation break is worse than no explanation, because it closes
the investigation.
