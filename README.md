# AI Agentic Engineer — Take-Home Submission

Response to `AI_Agentic_Engineer_Assignment.pdf`, using the messy mock data in
`inputs/` **unmodified**.

The built slice is a **TB → chart-of-accounts mapper** with confidence scoring
and human-in-the-loop escalation, runnable as a CLI or through a web UI. Both
modes call the same pipeline and produce byte-identical artifacts.

---

## Deliverables

| Deliverable | Location |
|---|---|
| Architecture document (§4.1) | [`architecture.md`](architecture.md) |
| How it was built | [`approach.md`](approach.md) — decisions, in order, and what each cost |
| Clarifying questions (§6) | [`clarifying-questions.md`](clarifying-questions.md) |
| Working prototype of one slice (§4.2) | [`coa_mapper/`](coa_mapper/) — CLI + HTTP API |
| Interactive UI | [`ui/`](ui/) — React + Vite |
| Output artifacts (§7) | [`output/`](output/) — committed from a real run |
| One-page reflection (§4.3) | [`reflection.md`](reflection.md) |

## Slice chosen, and why

Of the four slices offered I built **slice 1**:

> "TB → COA mapper that handles unmapped or ambiguous accounts with confidence
> scores and human-in-the-loop escalation."

It is the only one of the four where the agentic design question is genuinely
live. Statement generation from a resolved ledger is arithmetic; adjustment
validation is a rule engine. Mapping is where a system either guesses and is
quietly wrong, or scores its evidence, gates on a threshold, and escalates what
it cannot justify. That is the part worth building properly, and the part where
getting it wrong is invisible until an auditor finds it.

The other three slices are covered as design in `architecture.md`, not as code.

---

## Quick start

### Both modes at once (UI + API)

```bash
make install          # Python venv + package with dev/lint extras
npm run setup         # UI dependencies
npm run dev           # starts the API and the Vite dev server together
```

Open **http://localhost:5173**, click *Load bundled sample* → *Run mapping*. One
`ctrl-c` stops both processes.

### CLI only

```bash
cd coa_mapper
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

.venv/bin/coa-mapper run --config config.yaml      # reads ../inputs, writes ../output
```

**Requirements.** Python 3.11+ and — for the UI only — Node 20.19+. The pipeline
has exactly two runtime dependencies, `rapidfuzz` and `PyYAML`, in both modes:
the API is built on the standard library on purpose. No network access, no API
keys, no model calls.

---

## The two modes

Both are thin shells around the same `run(config)`. Neither reimplements any
policy, and a test asserts the artifacts are byte-identical between them.

### CLI

```bash
coa-mapper run   [--config config.yaml] [--inputs DIR] [--out DIR] [--entity NAME]
coa-mapper serve [--config config.yaml] [--host 127.0.0.1] [--port 8765]
```

Exit codes are the contract:

| Code | Meaning |
|---|---|
| `0` | clean pass |
| `1` | pass with disclosed exceptions — review queue and/or suspense present, nothing lost |
| `2` | hard failure — an ERROR finding, a failed verifier check, or a run that could not complete |

**On the provided data this exits `1`, and that is the correct result.** The
inputs contain real defects; the pipeline discloses them rather than papering
over them. Anything that stops the run completing — unreadable input, malformed
schema — is `2`, never `1`, so a CI wired *"fail on 2, review on 1"* can never
mistake a broken run for a reviewable one.

### UI

`npm run dev` runs `scripts/dev.mjs`, which supervises both processes: the Python
API on `:8765` and Vite on `:5173`, with `/api` proxied so the browser stays on
one origin. If either process dies the other is torn down, so you never end up
with a stray server holding a port.

The UI is a read-only audit surface over one run:

| Tab | What it shows |
|---|---|
| **Summary** | per-period counts and USD totals, input SHA-256s, the exact policy in force |
| **Decisions** | all 90 accounts, filterable by disposition/source/search; click any row for the full audit record |
| **Review & suspense** | proposals awaiting sign-off with runner-up and margin; suspense with dollar amounts and reasons |
| **Findings** | every detected defect, grouped ERROR / WARN / INFO |
| **Verification** | the 13 independent re-derivation checks |
| **Artifacts** | the same seven files the CLI writes, viewable and downloadable |

Clicking an account opens its decision record: the feature vector with weights,
the composite those exact numbers produce, flags, plain-English reasons, the
source rows the balance came from, and the FX rate applied to each.

Nothing is uploaded anywhere. The API runs locally, writes uploads to a temp
directory, and destroys it when the run finishes — it holds no state between
requests.

---

## What the run does

```
load → validate → FX-translate → tiered match → confidence gate → verify → emit
```

Matching runs in tiers, cheapest first, and every decision is arithmetic over
named features — **no LLM is involved**. Full design notes, the tier table, the
feature weights and the deliberate limits are in
[`coa_mapper/README.md`](coa_mapper/README.md).

On the provided data: 88 accounts resolve by exact code, `6905 Sundry Operating
Expenses` is proposed as `6900 Other Operating Expenses` at 0.8002 and queued for
a human, and `9999 Suspense - Unmapped` scores 0.3507 and is held in suspense
with its $12,400.00 attached.

Start reading the output at
[`output/validation_report.md`](output/validation_report.md).

---

## Defects found in the input data

The brief seeds some defects, states fewer than it seeds, and says so.

**Stated in the PDF:**

| Defect | Detail | How it is handled |
|---|---|---|
| TB unbalanced after FX | Break is **$182,460.20** — not rounding scale | **Not asserted by this slice.** A mapper's job is that every row lands somewhere justified, and it verifies exactly that. Debits = credits is a ledger-stage identity, designed in `architecture.md` §4. The mapper's own USD totals reproduce the figure exactly |
| Duplicate account code | `6310` Travel & Entertainment, two USD rows | Summed per convention, **and** WARNed as a double-post signature |
| Orphan TB account | `9999 Suspense - Unmapped`, not in COA | Suspense at 0.3507 with its **$12,400.00** attached — never dropped |
| Ambiguous COA category | `1150` and `2170` both `cf_category = TBD` | INFO finding; blocks Cash Flow only, reported as such |
| COA header with no children | `1290 Other Assets` | INFO finding |
| Adjustment debit ≠ credit | JE-002, $28,500 vs $25,000 | REJECT (designed; adjustments are not in this slice) |
| Adjustment to unknown account | JE-005 references `6315` | QUARANTINE (designed) |
| Circular intercompany entry | JE-008, both legs hit `2170` | QUARANTINE with hypothesis (designed) |
| Prior-period account renamed | `6905` → `6900` | Proposed at **0.8002** on 0.9429 balance continuity, queued for sign-off |
| Missing FX period-end rate | **GBP** has `period_average` only | Provisional fallback, every affected row tagged, disclosed, and the fallback set independently recomputed by the verifier |

**Not called out in the PDF, found while building:**

- **`8000 Income Tax Expense` is a leaf with no parent** — it sits outside the
  COA hierarchy, so any rollup walking parent links from the root omits it.
  Reported as `COA_ROOT_LEAF`.
- **`fx_rates.csv` carries an `opening` rate type** the brief never mentions, for
  EUR and GBP. Not valid for point-in-time balances, so it is loaded, ignored by
  policy, and the fact that it was ignored is disclosed rather than passed over.
- **The balance-sheet gap is not the TB break.** It is the break net of the
  excluded suspense account: `$182,460.20 − $12,400.00 = $170,060.20`. That only
  shows up once you build the statements.

---

## Verification

```bash
make check        # ruff + black --check + mypy, then tests, then reproduce
make test         # 136 tests
make coverage     # branch coverage, HTML report in coa_mapper/htmlcov
make reproduce    # fails if committed output/ is not what a fresh run produces
```

`make reproduce` is the one worth knowing about: it re-runs the pipeline into a
temp directory and diffs against the committed `output/`. A clean checkout
reproduces those artifacts **byte for byte**, and CI enforces it.

Beyond the test suite, the artifacts were audited against `inputs/` by
independent re-derivation that does not import the package — tier assignment,
every feature value, the composite scores, the runner-up rankings, row and USD
conservation, and the input hashes. See `reflection.md` for what that turned up.

---

## Repository layout

```
architecture.md            main artifact: topology, code/LLM boundary, failure
                           modes, validation loop, auditability
approach.md                how it was built: decisions in order, the input audit,
                           and the techniques that found bugs the tests missed
clarifying-questions.md    the 3 questions, and the assumption made for each
reflection.md              one page: 3 months vs 8 hours, scale limits, AI tools
inputs/                    provided mock data, unmodified
output/                    artifacts from a real run, committed
coa_mapper/                the slice
  src/coa_mapper/          pipeline, gate, matcher, verifier, api
  config/entities/         per-entity policy overrides
  tests/                   136 tests: golden, property, contract, API
ui/                        React + Vite audit interface
scripts/dev.mjs            supervises API + UI under one command
Makefile                   install / format / lint / test / coverage / reproduce
.github/workflows/ci.yml   the same gate on 3.11 and 3.12, 95% coverage floor
```

---

## How I used AI tools

Built with Claude (Claude Code) throughout. Where it helped, where it led me
wrong, and what I did not delegate are in [`reflection.md`](reflection.md) —
including several defects that only surfaced once linters, property-based tests
and independent re-derivation were pointed at code that already passed its own
test suite.
