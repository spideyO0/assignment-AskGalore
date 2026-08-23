# COA Mapper — deterministic TB → chart-of-accounts mapping

Slice 1 of the assignment brief: a **TB → COA mapper that handles unmapped or
ambiguous accounts with confidence scores and human-in-the-loop escalation**.

Zero LLM integration. Every decision is arithmetic over named features,
reproducible byte-for-byte, and auditable end to end. Two runtime dependencies —
`rapidfuzz` and `PyYAML` — whether you run the CLI or the API.

## Design

```
load → validate → FX-translate → tiered match → confidence gate → verify → reconcile-failures → emit
```

Matching runs in tiers, cheapest first:

| Tier | Rule | Outcome |
|---|---|---|
| `EXACT_CODE` | account code exists in COA leaves | AUTO_APPLIED @ 1.0000 |
| `NORMALIZED_NAME` | canonical (stopword-stripped) name uniquely matches one leaf | AUTO_APPLIED @ 0.9900 unless vetoed |
| `FUZZY_COMPOSITE` | weighted score over features below | gated by thresholds |
| `NO_CANDIDATE` / `UNTRANSLATABLE` | nothing scores above the review floor / no FX rate exists | SUSPENSE with $ amount, never dropped |

Composite score = weighted mean of available features (weights renormalized when
evidence is missing):

- `name_similarity` (0.45) — rapidfuzz ratio/token_sort on normalized names
- `token_overlap` (0.15) — Jaccard over significant tokens
- `code_proximity` (0.10) — shared leading digits between codes
- `balance_continuity` (0.30) — `1 − |Δ|/max(|a|,|b|)` between the source balance
  and the candidate's balance in the *other* period; this is what catches the
  seeded rename `6905 Sundry Operating Expenses` → `6900 Other Operating Expenses`
  without any model

Hard rules layered on top:

- **Normal-balance veto**: proposed target's normal balance conflicts with the
  observed dominant side ⇒ never auto-applied, goes to REVIEW with the numbers.
- **Ambiguity guard**: top candidate leads the runner-up by less than
  `tie_epsilon` ⇒ REVIEW even above the auto threshold.
- **No FX rate at all** ⇒ rows routed to suspense as ERROR findings. A missing
  rate is never invented. An account only *partly* untranslatable (say a JPY row
  beside EUR and GBP rows) is dispositioned once, carrying the translatable
  subtotal, with the reason stating plainly that the figure is partial — an
  understated-but-labelled number, never a confident zero.
- **COA parent cycles** are ERROR findings. Any rollup walking parent links would
  recurse forever, so a structurally impossible chart fails the run rather than
  passing as reviewable.

## Run — CLI

Python 3.11+. Dependencies: `rapidfuzz`, `PyYAML` (plus `pytest`, `hypothesis`
for the dev extra). No network, no API keys, no model calls.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/coa-mapper run --config config.yaml          # reads ../inputs, writes ../output
.venv/bin/python -m pytest tests/ -q                   # 136 tests
```

Override paths per run without touching config: `--inputs <dir>`, `--out <dir>`.
Layer a per-entity policy with `--entity <name>`.

Exit codes: `0` clean pass · `1` pass with disclosed exceptions · `2` hard failure.
Anything that stops the run completing — unreadable input, malformed schema — is
`2`. A failure never exits `1`, so "review on 1" can never swallow a broken run.
**Expect `1` on the provided data** — the inputs carry real defects and the run
discloses them. Wire CI as "fail on `2`, review on `1`".

Tunable in `config.yaml`: `auto_min` (0.90), `review_min` (0.60), `tie_epsilon`
(0.03), `top_k` (3), `max_suspense_ratio` (0.50 — past this share of accounts or
of USD in suspense the run is a hard failure, because total mapping collapse is
not "exceptions to review"), the four feature weights, and input/output paths.
Every run echoes the config it used into the validation report, so an artifact
always names the policy that produced it.

## Run — API / UI

```bash
.venv/bin/coa-mapper serve --port 8765
```

| Route | Purpose |
|---|---|
| `GET /api/health` | liveness |
| `GET /api/sample` | the bundled `inputs/` as `{name: content}`, for one-click demo |
| `GET /api/entities` | available per-entity policies |
| `POST /api/run` | `{files: {name: content}, entity?}` → full result |

The API is standard-library only and stateless: uploads land in a temp directory,
the pipeline runs, artifacts come back in memory, the directory is destroyed. It
calls the same `run(config)` the CLI does and reimplements no policy — a test
asserts the seven artifacts are **byte-identical** between the two modes.

A pipeline that ran and reported a hard failure is a successful HTTP exchange
reporting a bad run: the exit code is in the payload. Only a malformed request is
a 4xx.

The React UI lives in [`../ui`](../ui); `npm run dev` from the repo root starts
both processes together.

## Per-entity policy (`config/entities/`)

One global `auto_min` is the wrong shape at scale — the tolerable false-auto-map
rate differs by chart and by account class. Policy therefore lives per entity,
versioned next to the code, layered over the base config:

```bash
.venv/bin/coa-mapper run --config config.yaml --entity acme_us
```

Only keys present in the entity file override the base; weights merge rather than
replace. The active entity is echoed into the validation report. An unknown
`--entity` is a hard failure listing what *is* available — silently falling back
to base thresholds would apply the wrong policy under the entity's name.
`_template.yaml` documents the format.

## Optional semantic feature (`semantic.py`)

The mapper needs no model on this data, and ships with none configured. When a
provider *is* configured, its score enters the **same weighted vector** as
`name_similarity` and the rest — same `auto_min` gate, same normal-balance veto,
same tie guard, written into `decisions.jsonl` like any other feature. Swapping
the provider changes a number, not the control flow.

That is deliberately unlike the common pattern of asking a model for its own
`"confidence": "high|medium|low"` and applying the classification regardless: a
model's estimate of its own certainty is not a probability of anything, so here
it is evidence to be weighed, never a gate to be trusted.

Reproducibility is enforced rather than hoped for. Every lookup is
content-addressed on (cache version, provider id, prompt version, both account
names), with a TTL and hit/miss accounting; a cache-version bump discards rather
than migrates. In `strict=True` mode a miss **raises** instead of calling out, so
CI either reproduces from the committed cache byte-for-byte or fails loudly. With
no provider configured the feature is never emitted, the weights renormalize over
what remains, and the artifacts are byte-identical to a build without the module.

## Outputs (`../output/`, at the repo root per assignment §7)

| File | Contents |
|---|---|
| `mapped_tb_current.csv` / `_prior.csv` | every input row: FX rate + origin, USD amounts, `applied_*` (populated **only** when AUTO_APPLIED), `proposed_*` (top candidate whatever the disposition), tier, confidence, disposition |
| `review_queue.csv` | proposed mappings awaiting human sign-off, with runner-up and margin |
| `suspense.csv` | excluded rows with $ amounts and reasons — visible, never dropped |
| `decisions.jsonl` | full audit record per account: feature vector, weights, flags, reasons, row ids |
| `validation_report.md` | status, input hashes, reconciliation math, findings, verifier results |
| `summary.json` | machine-readable counts + totals + exit code |

## Verification (independent re-derivation)

The verifier reloads raw inputs from disk, recomputes aggregates, re-runs the
gate, and checks the pipeline's answers against its own:

- row conservation — every input row claimed exactly once, no overlaps
- USD conservation — Σ\|net\| decomposes exactly across dispositions
- decision reproduction — independent re-run diverges on zero accounts
- auto-gate integrity — no AUTO_APPLIED below threshold or carrying a veto flag
- FX fallbacks flagged — independently recomputed fallbacks ⊆ disclosed findings
- idempotent render — artifacts rendered twice are byte-identical

On the provided messy data this yields exit `1` with: `9999 Suspense - Unmapped`
($12,400) held in suspense; prior-period `6905` proposed to `6900` at 0.8002
confidence (continuity evidence 0.9429) queued in review; duplicate `6310` summed
but WARNed as a double-post signature; GBP translated at period-average fallback
and flagged (no period-end rate); COA structural notes (`1150`/`2170` TBD
categories, childless header `1290`, parentless leaf `8000`) reported.

## Deliberate limits

- `applied_code` and `proposed_code` are separate columns on purpose. A single
  `mapped_code` column made a rejected 0.3507-confidence candidate for
  `9999 Suspense - Unmapped` read as an applied mapping to `1140 Prepaid Expenses`.
  Summing by `applied_code` now reproduces the AUTO_APPLIED total exactly, so no
  suspense or review dollar can leak into a downstream mapping table
  (`tests/test_applied_vs_proposed.py`).
- Headers are not mapping targets; TB accounts map to COA leaves only.
- Point-in-time balances use `period_end`; `opening` rates are loaded and ignored
  by policy (INFO finding), `period_average` is the only sanctioned fallback.
- Same-code multi-row accounts are summed per the stated convention and WARNed,
  because the identical pattern is the signature of an accidental double-post;
  disambiguation needs the source system.
- The matcher is O(n·m) with no candidate blocking. Correct at 90 accounts, wrong
  at 5,000 — see `../reflection.md`.
