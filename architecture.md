# Architecture: AI-Agentic Financial Statement Generation

Response to `AI_Agentic_Engineer_Assignment.pdf` §4.1. The system described
here ingests a trial balance, a chart of accounts, and a batch of manual
adjustments, and produces the four statements (Balance Sheet, P&L, Cash
Flow, SOCIE) with audit-grade traceability.

One slice of it is built for real: the **TB → COA mapper** (§4.2, slice 1),
in `coa_mapper/`, runnable as a CLI or through the React UI in `ui/`.
Everything else in this document is design, not code, and is labelled as such.
Where a section describes something the prototype actually does, it says so and
points at the file.

For *how* it was built — the order decisions were made in, what the input audit
turned up, and the four techniques that found bugs the test suite could not —
see [`approach.md`](approach.md).

---

## 0. Three clarifying questions, and what I assumed instead

The brief allows up to three questions before starting. Mine are in
[`clarifying-questions.md`](clarifying-questions.md), with the assumption I
made for each so the work could proceed unblocked.

The distinction worth stating up front: **none of the seeded data defects
are questions.** A missing FX rate, an unmapped account, an unbalanced
journal entry, a circular intercompany entry — those are handled unattended
by design, with the outcome disclosed rather than guessed (§3). What
genuinely cannot be inferred from the CSVs is a small set of
*accounting-policy* choices, which are facts about the business rather than
facts about the data. Those are the three questions. They are documented
assumptions, not blockers, and each is isolated to a specific line item so a
reviewer can override one without re-running anything else.

## 1. Framing: this is six problems, not one

"Generate the financial statements" decomposes into at least six
sub-problems with genuinely different reliability requirements and genuinely
different right tools:

| # | Sub-problem | Reliability need | Right tool |
|---|---|---|---|
| 1 | Parse and validate source files (schema, types, encodings) | Must never silently accept garbage | Deterministic code |
| 2 | Map TB accounts to COA nodes, including unmapped/ambiguous/renamed ones | Needs judgment on fuzzy names, must never guess silently | Scored proposal + threshold gate + human queue. LLM optional, and only as one more scored feature |
| 3 | FX translation | Must be exactly correct or explicitly flagged | Deterministic code + explicit policy for gaps |
| 4 | Validate and disposition manual adjustments | Needs to interpret memos and produce human-readable explanations | Rule engine decides ACCEPT/REJECT/QUARANTINE. LLM drafts the plain-English explanation and triages semantically odd entries a rule cannot catch |
| 5 | Roll TB + adjustments into the four statements | Pure arithmetic once #2–#4 resolve | Deterministic code, zero LLM |
| 6 | Verify the output and emit an audit trail | Must never rubber-stamp its own work | Independent re-derivation against accounting identities |

The rest of this document treats each as a distinct stage with its own typed
contract, rather than one prompt that ingests a TB and hopes.

Sub-problem #2 is the slice I built, because it is the one where the
"agentic" question is actually live. #5 is arithmetic; #1 and #3 are
plumbing. #2 is where a system either guesses and is wrong quietly, or
scores, gates, and escalates.

## 2. Agent topology: deterministic orchestrator, narrow sub-agents, no swarm

**Choice:** a deterministic orchestrator — plain code, not an LLM — calling a
small number of narrowly scoped stages in a fixed pipeline, each with a typed
input and output contract:

```
Loader → FX Translator → COA Mapper → Adjustments Agent → Ledger Builder
       → Statement Builder → Verifier → Audit Trail Writer
```

- **Loader, FX Translator, Ledger Builder, Statement Builder** are pure code.
  No model call, no non-determinism, fully unit-testable. This is most of the
  pipeline by line count *and* by dollar value at risk.
- **COA Mapper** and **Adjustments Agent** are the only two stages where
  judgment is genuinely required — fuzzy account names, renamed accounts,
  ambiguous memos, novel entry patterns. They are the only two candidates for
  LLM involvement, and even there a model's output is a *proposal with a
  confidence score*, never a posted number. A deterministic gate decides
  auto-apply / escalate / suspend.
- **Verifier** is a separate stage from the one that produced the numbers, on
  purpose. An agent that checks its own arithmetic with the same reasoning it
  used to produce it reproduces its own blind spots. The verifier knows only
  accounting identities and re-derives from the raw inputs (§5).

**Why not one agent with tools.** A mega-agent free-reasoning over the whole
TB conflates problems with wildly different risk profiles — parsing a CSV
versus deciding whether a circular intercompany entry is real. It also makes
the arithmetic non-reproducible: you cannot unit-test whether the LLM added
the balance sheet correctly and get the same answer twice under load. The
brief calls this out as a red flag and I agree with the framing.

**Why not a twelve-agent swarm.** A swarm (Mapper, Adjuster, Builder,
Validator, plus one agent per statement, per currency, per entity) adds
coordination overhead — state handoff, retries, partial-failure semantics —
for work a ~2,000-line deterministic pipeline already does correctly and
cheaply. Every seeded defect in this dataset (duplicate code, orphan account,
ambiguous category, missing rate, unbalanced JE, circular IC entry) is
*detectable with a rule*. Two narrow judgment points plus a strict
orchestrator is the right amount of agentic surface area. More would be
theatre.

**Two front doors, one pipeline.** The slice ships a CLI and an HTTP API behind
a React UI. Neither is a second implementation: both call the same
`run(config)`, and a test asserts the seven artifacts are byte-identical between
them. This matters more than it sounds — a review interface that computes
slightly different numbers than the batch job is worse than no interface,
because it teaches people to distrust whichever one they are not looking at. The
API is standard-library only and stateless (uploads to a temp directory,
destroyed per request), so the two-dependency claim holds in both modes, and the
UI is read-only by design: it makes a run inspectable without becoming a second
place where policy lives.

**What "agent" means in the built slice.** The mapper is an agent in the
sense that matters operationally: it perceives (features over TB and COA),
proposes (ranked candidates with confidence), decides under an explicit
policy (threshold gate + hard vetoes), escalates what it cannot decide
(review queue), and refuses to act when it has no basis (suspense). It does
that with zero LLM calls. That is the point of §3.

## 3. Where deterministic code stops and the LLM earns its keep

Generating a balance sheet from a **clean** TB is arithmetic: group, sum,
sign-convert, roll up a tree. Zero LLM involvement is correct there.

The interesting claim from building the mapper slice is stronger than I
expected going in: **on this dataset, the judgment stage does not need an LLM
either.** The seeded rename — prior-period `6905 Sundry Operating Expenses`
versus current `6900 Other Operating Expenses` — is caught by a named,
weighted feature vector:

| Feature | Weight | What it contributes |
|---|---|---|
| `name_similarity` | 0.45 | rapidfuzz ratio / token_sort over stopword-normalised names |
| `balance_continuity` | 0.30 | `1 − |Δ| / max(|a|,|b|)` against the same account's balance in the *other* period |
| `token_overlap` | 0.15 | Jaccard over significant tokens |
| `code_proximity` | 0.10 | shared leading digits |

`6905 → 6900` scores 0.8002, driven by 0.9429 balance continuity, and lands
in the review queue rather than being auto-applied — which is the correct
outcome, because 0.80 is exactly the confidence band where a human should
look. An LLM asked the same question would return a similar answer with a
number attached that is not a probability of anything, and would not be
reproducible run to run.

So the honest boundary is not "code for arithmetic, LLM for judgment". It is:

**Use an LLM only where the evidence is unstructured text that no feature can
score.** Concretely, three places:

1. **A tie-break feature, not a decision.** Where the COA carries prose
   descriptions and the account name alone is uninformative
   (`9999 Suspense - Unmapped` is the example in this data — it scores 0.3507
   and goes to suspense, correctly, because there is nothing to match on), an
   embedding similarity or an LLM judgment can enter the *same weighted
   vector* as one more feature with its own weight, subject to the same
   threshold gate and the same hard vetoes. It never becomes its own code
   path. This preserves the property that matters: every decision is explained
   by a feature vector written to `output/decisions.jsonl`, and swapping the
   LLM out changes a number in that vector rather than changing the control
   flow.
2. **Explaining a rejection to a finance user, in plain English.** A rule
   engine can say debits ≠ credits by $3,500. It takes a model — or a human —
   to say that $3,500 looks like it was dropped between two related reclass
   lines and suggest checking it against the T&E line it was meant to net
   against. The prototype's `reason` strings are hand-written in exactly the
   style an LLM-drafted explanation should follow: cite the number, cite the
   source, say what to do next. In a full build the model drafts that text
   *from the rule's structured finding*, never from raw judgment, and a human
   can regenerate it without touching disposition logic.
3. **Triaging patterns no rule covers.** Rules catch what you anticipated.
   The value of a model here is proposing *hypotheses* about entries that
   pass every rule and are still wrong — and routing them to a human, not
   acting on them.

Everything else — FX translation, hierarchy rollup, tolerance checks, header
reconciliation — is arithmetic against explicit source-of-truth data. An LLM
there adds latency, cost, and a hallucination failure mode to a problem with
one deterministically correct answer. It has no business in that path.

## 4. Failure modes and how the design handles each

| Failure mode | Where it shows up in the actual data | Handling | Built? |
|---|---|---|---|
| **Hallucinated account mapping** | Would show as `9999` being confidently mapped to a real account | Nothing auto-applies below `auto_min` (0.90). A **normal-balance veto** blocks auto-apply when the candidate's normal balance conflicts with the observed dominant side. A **tie guard** forces review when the top candidate leads the runner-up by less than `tie_epsilon` (0.03) even above threshold. `9999` scores 0.3507 → suspense with its $12,400.00 attached | ✅ `gate.py` |
| **Account fits no COA node** | TB `9999 Suspense - Unmapped` ($12,400.00); JE-005 references `6315` | Routed to suspense with the dollar amount, reason, and feature vector. Excluded from applied mappings, **never dropped** — row and USD conservation are verified (§5) | ✅ mapper / ⬜ JE path |
| **Renamed account across periods** | prior `6905` vs current `6900` | `balance_continuity` feature proposes it at 0.8002; below `auto_min`, so it queues for sign-off with runner-up and margin shown. History is never silently spliced | ✅ `features.py` |
| **FX gaps (missing rate)** | GBP has no `period_end` row in `fx_rates.csv` | Provisional fallback to `period_average`, every affected row tagged with rate origin, disclosed as a `FX_PERIOD_END_FALLBACK` finding, and the fallback set is **independently recomputed** by the verifier and checked against what was disclosed. If *no* rate of any kind exists, rows go to suspense as `UNTRANSLATABLE` — a rate is never invented | ✅ `fx.py` |
| **Duplicate source rows** | TB `6310` appears twice in USD | Summed per the stated convention, but also flagged `DUP_ACCOUNT_CURRENCY`, because the identical pattern is the signature of an accidental double-post. Disambiguating the two cases needs the source system, not this pipeline | ✅ `pipeline.py` |
| **Debits ≠ credits after adjustments** | JE-002 ($28,500 vs $25,000) | Per-entry balance check before posting. REJECT with both numbers and the delta. Never partially post one leg | ⬜ designed |
| **Circular intercompany entry** | JE-008, both legs hit `2170`, nets to zero | Detected structurally (all lines net to zero across the same account set), QUARANTINE with a specific hypothesis — wrong contra-account — rather than posted as a no-op | ⬜ designed |
| **Unexplained TB break** | TB is out by **$182,460.20** after FX translation, before any adjustment | Never plugged into a miscellaneous line. Disclosed exactly, with the balance sheet allowed to visibly not balance and the gap decomposed into its component causes (§6) | ⬜ designed |
| **Ambiguous COA metadata** | `1150` and `2170` have `cf_category = TBD`; `1290 Other Assets` is a header with no children; `8000` is a leaf with no parent | Reported as INFO findings. Does not block BS/P&L; **does** block the Cash Flow Statement, and is surfaced as such rather than defaulted to "Operating" | ✅ `coa.py` |
| **Structurally impossible COA** | A parent cycle, or a subtree whose parent is not in the chart | A cycle is an ERROR: any rollup walking parent links recurses forever, so the run fails rather than passing as reviewable. A missing parent is a WARN — an unreachable subtree is a data problem, not a non-terminating one. Reported once per cycle, not once per member | ✅ `coa.py` |
| **Mapping collapse presented as routine** | A chart with no usable targets sends every account to suspense | Exit codes are otherwise presence-based, so one suspense row and ninety are indistinguishable. Past `max_suspense_ratio` (0.50 of accounts *or* of USD) the run is a hard failure: nothing was dropped, but at that rate the mapping has failed rather than produced exceptions | ✅ `pipeline.py` |

The throughline: **every failure mode either gets a hard rule (reject or
quarantine, with a number attached) or gets disclosed with a quantified gap.
Nothing is silently corrected, defaulted, or dropped.**

## 5. The validation and self-correction loop

### What the agent checks before returning output

The built verifier (`verifier.py`) does not read the pipeline's conclusions
and nod. It **reloads the raw inputs from disk and recomputes**, then compares:

| Check | What it proves |
|---|---|
| `row_conservation` | Every input row is claimed by exactly one decision — no missing, no extra, no overlap |
| `usd_conservation` | Σ\|net USD\| decomposes exactly across AUTO_APPLIED + REVIEW + SUSPENSE, no remainder |
| `decision_reproduction` | An independent re-run of the gate diverges on zero accounts |
| `auto_gate_integrity` | Nothing is AUTO_APPLIED below threshold or while carrying a veto flag |
| `fx_fallbacks_flagged` | Fallbacks recomputed from raw rates ⊆ fallbacks disclosed in findings |
| `idempotent_render` | Artifacts rendered twice are byte-identical |

For the full system, the same pattern extends to the accounting identities
the *builder* must not be trusted to re-derive: debits = credits post-FX,
Assets = Liabilities + Equity, leaf-sum = header total, every adjustment has
a disposition, every excluded account is visible with its amount.

### What happens when a check fails

The pipeline **does not halt, and does not retry with different assumptions
hoping to converge on a balance.** It downgrades the run to
`PASS WITH DISCLOSED EXCEPTIONS` (exit code 1), keeps every number that is
trustworthy, and attaches a root-cause hypothesis to every number that is
not. Exit codes are the contract: `0` clean, `1` disclosed exceptions,
`2` hard failure.

The self-correction that matters is not "try again". It is **turning a failed
check into a scoped, assignable investigation.** Worked example from this
dataset, derived by hand from the provided files:

```
TB break after FX translation                    $182,460.20
less suspense account 9999 (excluded, disclosed)  $12,400.00
                                                 ────────────
residual gap carried to the balance sheet        $170,060.20
```

The right output is not "the numbers don't add up". It is "the numbers don't
add up by exactly $170,060.20, which is these two known causes and nothing
else" — so a reviewer can check the arithmetic themselves instead of
trusting the tool. A gap that fully decomposes is a ticket. A gap that does
not decompose is a stop-the-close event, and should be reported as one.

A harder failure — an adjustment referencing a nonexistent account, or a
non-balancing entry — never reaches the ledger at all. It is stopped at the
adjustments stage, before it can corrupt a statement.

## 6. Auditability: tracing any cell back to source rows

Every number is a lookup into a lineage record produced *at the same time* as
the number, not reconstructed afterwards. In the built slice:

- **`output/mapped_tb_current.csv` / `_prior.csv`** — every input row with the
  FX rate applied, the rate's origin (`period_end`, `period_average_fallback`,
  `usd_functional`), USD amounts, mapped code, tier, confidence, disposition.
- **`output/decisions.jsonl`** — one record per account carrying the complete
  basis for the decision: feature vector, weights used, flags, runner-up and
  margin, human-readable reasons, and the exact source `row_ids`. This is the
  artifact that makes the mapping defensible, e.g.:

  ```json
  {"account_code": "1110", "disposition": "AUTO_APPLIED", "tier": "EXACT_CODE",
   "confidence": "1.0000", "usd_net": "5674960.20",
   "rate_notes": ["USD:usd_functional", "EUR:period_end", "GBP:period_average_fallback"],
   "row_ids": ["current:2", "current:3", "current:4"]}
  ```

- **`output/review_queue.csv`** — proposals awaiting sign-off, with runner-up
  and margin, so the human sees what the machine *almost* chose.
- **`output/suspense.csv`** — excluded rows with amounts and reasons.
- **`output/validation_report.md`** — status, SHA-256 of every input file,
  reconciliation math, findings, verifier results.

Input hashing is what makes the trail reproducible rather than merely
verbose: an auditor can confirm that this report describes *these* files.

For the full system, the same discipline extends one level up: a statement
line resolves to its posted-ledger account, which resolves to its TB source
rows plus the journal entries posted on top. Tracing a $6,250,000 Salaries
line resolves to TB row 40 ($5,400,000) plus JE-001 "Bonus accrual"
($850,000). This is why FX translation and adjustment posting stay separate
inspectable stages rather than collapsing into one "compute the balance"
step. Collapsing them still gets the right number and destroys exactly this
traceability.

## 7. The other three statements

Not built, and worth being explicit about what each actually needs beyond
the Balance Sheet and P&L:

- **Cash Flow.** Blocked on data, not on design: `cf_category` is `TBD` for
  `1150` and `2170`. The indirect method needs every balance-sheet movement
  classified Operating / Investing / Financing, so two unclassified accounts
  are two unplaceable deltas. The correct behaviour is to refuse to emit the
  statement and name the two accounts — not to default them to Operating,
  which is the silent-corruption failure this whole design exists to avoid.
- **SOCIE.** Needs the opening → closing equity walk, so it needs the prior
  period mapped to the same COA — which is precisely why the mapper runs over
  both `trial_balance.csv` and `prior_period_tb.csv`, and why the `6905 → 6900`
  rename must be resolved by a human before comparatives mean anything.
  An unresolved rename silently breaks the walk.
- **Balance Sheet / P&L.** Arithmetic once mapping and adjustments resolve.
  The design requirement worth stating: sections are rolled up by **section
  polarity**, and membership is derived from the COA's own `statement` and
  `account_type` columns rather than from any list of account codes held in
  code. A chart is data; a chart baked into source is a chart that silently
  stops matching the one the client sends. `8000` in this dataset — a leaf with
  no parent — is exactly the account such a list would omit.

## 8. What this design deliberately does not do

- **It does not use an LLM to decide whether debits equal credits, whether the
  balance sheet balances, or how to translate currency.** Those have exactly
  one correct answer, and a model can only get them right by accident or
  wrong with confidence.
- **It does not force the balance sheet to balance.** A forced balance is a
  lie dressed as a checkmark. A disclosed, quantified gap is usable output.
- **It does not retry with a different model or prompt when a deterministic
  check fails.** Retrying non-deterministic reasoning against a deterministic
  failure does not fix the unbalanced entry — it hides how it was fixed.
- **It does not map to header accounts.** TB accounts map to COA leaves only;
  headers are rollup targets, not posting targets.
- **It does not invent an FX rate.** Missing period-end falls back to
  period-average *and says so*; missing everything routes to suspense.
