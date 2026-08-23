# COA Mapper UI

React + Vite front end for the mapper. A **read-only audit surface** over one
pipeline run — it makes a run inspectable, it does not change one.

## Run

From the repo root, both processes together:

```bash
npm run setup     # once: installs UI dependencies
npm run dev       # API on :8765, Vite on :5173
```

Or the UI alone, against an API you started yourself:

```bash
cd ui && npm run dev          # expects the API on http://127.0.0.1:8765
COA_API=http://host:port npm run dev    # or point it elsewhere
```

`/api` is proxied by Vite so the browser stays on one origin — no CORS in the
loop, and the same relative paths work if the built bundle is served from any
static host.

## What it shows

| Tab | Content |
|---|---|
| Summary | per-period counts and USD totals, input SHA-256s, the policy in force including feature weights |
| Decisions | every account, filterable by disposition / source / free text; click a row for the audit record |
| Review & suspense | proposals awaiting sign-off with runner-up and margin; suspense with amounts and reasons |
| Findings | detected defects grouped ERROR / WARN / INFO |
| Verification | the independent re-derivation checks |
| Artifacts | the same files the CLI writes, viewable and downloadable |

The decision drawer is the point of the whole interface: feature vector with the
weight applied to each, the composite those exact numbers produce, flags,
plain-English reasons, the source rows the balance came from, and the FX rate and
its origin per row. Everything an auditor would ask, from the record itself.

## What it deliberately does not do

**Editing.** You cannot approve a review item or override a mapping. Persisting
human decisions is a real feature — it needs author, timestamp, provenance, and
an idempotency story where a resolved item applies at confidence 1.0 on the next
run. A button that looked like it did that but forgot it on reload would be worse
than not having one. See `../reflection.md`.

## Notes

- Nothing is uploaded anywhere. The API is local and stateless: files go to a
  temp directory, the run happens, the directory is destroyed.
- Vite binds `127.0.0.1` explicitly. Its default `localhost` resolves to `::1`
  first on Node 17+, which leaves the dev server listening on IPv6 only and every
  IPv4 client getting connection refused against a server that is running.
- `npm run build` emits a static bundle to `dist/`; it needs the API reachable at
  `/api` wherever it is served from.
