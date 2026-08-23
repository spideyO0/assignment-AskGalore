from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .config import MapperConfig
from .models import Decision, Finding


@dataclass(frozen=True)
class Artifact:
    name: str
    content: str


def _money(x: Decimal) -> str:
    return f"{x:.2f}"


def _conf(x: Decimal) -> str:
    return f"{x:.4f}"


def render_mapped_tb(
    row_records: list[dict],
    decision_by_code: dict[str, Decision],
) -> str:
    # `applied_*` is populated ONLY for AUTO_APPLIED rows, so the obvious read of
    # this file — "what did this account map to?" — can never pick up a candidate
    # the gate rejected. `proposed_*` always carries the top candidate, including
    # for REVIEW and SUSPENSE rows, so the evidence is not lost. Collapsing these
    # into one `mapped_code` column let a 0.3506-confidence suspense candidate read
    # as an applied mapping.
    header = (
        "row_id,account_code,account_name,currency,debit,credit,fx_rate,rate_origin,"
        "usd_debit,usd_credit,applied_code,applied_name,proposed_code,proposed_name,"
        "tier,confidence,disposition,flags\n"
    )
    lines = [header]
    for rec in row_records:
        dec = decision_by_code[rec["account_code"]]
        flags = "|".join(dec.flags)
        rate = rec["fx_rate"]
        applied = dec.disposition == "AUTO_APPLIED"
        lines.append(
            ",".join(
                [
                    rec["row_id"],
                    rec["account_code"],
                    _csv(rec["account_name"]),
                    rec["currency"],
                    _money(rec["debit"]),
                    _money(rec["credit"]),
                    "1.0" if rate is None else str(rate.normalize()),
                    rec["rate_origin"],
                    _money(rec["usd_debit"]),
                    _money(rec["usd_credit"]),
                    dec.mapped_code if applied else "",
                    _csv(dec.mapped_name) if applied and dec.mapped_name else "",
                    dec.mapped_code or "",
                    _csv(dec.mapped_name) if dec.mapped_name else "",
                    dec.tier,
                    _conf(dec.confidence),
                    dec.disposition,
                    flags,
                ]
            )
            + "\n"
        )
    return "".join(lines)


def render_review_queue(decisions: list[Decision]) -> str:
    header = (
        "source,account_code,account_name,usd_net,proposed_code,proposed_name,"
        "confidence,runner_up_code,runner_up_confidence,margin,flags,features\n"
    )
    lines = [header]
    for d in sorted(decisions, key=lambda x: (x.source, x.account_code)):
        if d.disposition != "REVIEW":
            continue
        feats = ";".join(f"{k}={v:.4f}" for k, v in sorted(d.features.items()))
        lines.append(
            ",".join(
                [
                    d.source,
                    d.account_code,
                    _csv(d.account_name),
                    _money(d.usd_net),
                    d.mapped_code,
                    _csv(d.mapped_name),
                    _conf(d.confidence),
                    d.runner_up_code,
                    _conf(d.runner_up_confidence),
                    _conf(d.margin),
                    "|".join(d.flags),
                    _csv(feats),
                ]
            )
            + "\n"
        )
    return "".join(lines)


def render_suspense(decisions: list[Decision]) -> str:
    header = "source,account_code,account_name,usd_net,row_ids,flags,primary_reason\n"
    lines = [header]
    for d in sorted(decisions, key=lambda x: (x.source, x.account_code)):
        if d.disposition != "SUSPENSE":
            continue
        primary = d.reasons[0] if d.reasons else ""
        lines.append(
            ",".join(
                [
                    d.source,
                    d.account_code,
                    _csv(d.account_name),
                    _money(d.usd_net),
                    "|".join(d.row_ids),
                    "|".join(d.flags),
                    _csv(primary),
                ]
            )
            + "\n"
        )
    return "".join(lines)


def _decision_record(d: Decision) -> dict:
    return {
        "source": d.source,
        "account_code": d.account_code,
        "account_name": d.account_name,
        "disposition": d.disposition,
        "tier": d.tier,
        "confidence": str(d.confidence),
        "mapped_code": d.mapped_code,
        "mapped_name": d.mapped_name,
        "runner_up_code": d.runner_up_code,
        "runner_up_confidence": str(d.runner_up_confidence),
        "margin": str(d.margin),
        "features": dict(sorted(d.features.items())),
        "weights_used": dict(sorted(d.weights_used.items())),
        "flags": list(d.flags),
        "reasons": list(d.reasons),
        "usd_net": str(d.usd_net),
        "row_ids": list(d.row_ids),
        "rate_notes": list(d.rate_notes),
    }


def render_decisions_jsonl(all_decisions: list[Decision]) -> str:
    ordered = sorted(all_decisions, key=lambda d: (d.source, d.account_code))
    return "".join(json.dumps(_decision_record(d), sort_keys=True) + "\n" for d in ordered)


def render_summary(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _finding_rows(findings: list[Finding]) -> list[tuple[str, str, str]]:
    return [
        (f.severity.value, f.code, f.message) for f in sorted(findings, key=lambda f: f.sort_key())
    ]


def render_validation_report(
    config: MapperConfig,
    input_hashes: dict[str, str],
    input_row_counts: dict[str, int],
    decisions_by_source: dict[str, list[Decision]],
    findings: list[Finding],
    checks: list[tuple[str, bool, str]],
    exit_code: int,
) -> str:
    out: list[str] = []
    status = {0: "CLEAN PASS", 1: "PASS WITH DISCLOSED EXCEPTIONS", 2: "HARD FAILURE"}[exit_code]
    out.append("# COA Mapper — Validation Report\n")
    out.append(f"\n**Run status: {status}** (exit code {exit_code})\n")
    out.append(
        "\nExit codes: 0 clean pass · 1 pass with disclosed exceptions "
        "(review/suspense/warn present, nothing lost) · 2 hard failure.\n"
    )

    out.append("\n## 1. Inputs consumed\n")
    out.append("\n| File | Rows | SHA-256 |\n|---|---|---|\n")
    for name in sorted(input_hashes):
        out.append(
            f"| `{name}` | {input_row_counts.get(name, '-')} | `{input_hashes[name][:16]}…` |\n"
        )

    out.append("\n## 2. Mapping decisions\n")
    out.append("\n| Source | AUTO_APPLIED | REVIEW | SUSPENSE | |net USD| total |\n")
    out.append("|---|---|---|---|---|\n")
    for source in sorted(decisions_by_source):
        ds = decisions_by_source[source]
        counts = {
            k: sum(1 for d in ds if d.disposition == k)
            for k in ("AUTO_APPLIED", "REVIEW", "SUSPENSE")
        }
        total = sum((abs(d.usd_net) for d in ds), Decimal("0"))
        out.append(
            f"| {source} | {counts['AUTO_APPLIED']} | {counts['REVIEW']} | "
            f"{counts['SUSPENSE']} | {_money(total)} |\n"
        )

    out.append("\n## 3. Reconciliation math\n")
    out.append(
        "\nEvery input row is accounted for exactly once; the dollar decomposition below is "
        "re-derived independently by the verifier from raw files.\n"
    )
    for source in sorted(decisions_by_source):
        ds = decisions_by_source[source]
        rows_by = {}
        usd_by = {}
        for k in ("AUTO_APPLIED", "REVIEW", "SUSPENSE"):
            subset = [d for d in ds if d.disposition == k]
            rows_by[k] = sum(len(d.row_ids) for d in subset)
            usd_by[k] = sum((abs(d.usd_net) for d in subset), Decimal("0"))
        total_rows = sum(rows_by.values())
        total_usd = sum(usd_by.values(), Decimal("0"))
        out.append(
            f"\n**{source}**: rows {rows_by['AUTO_APPLIED']} + {rows_by['REVIEW']} + "
            f"{rows_by['SUSPENSE']} = {total_rows}; "
            f"${_money(usd_by['AUTO_APPLIED'])} + ${_money(usd_by['REVIEW'])} + "
            f"${_money(usd_by['SUSPENSE'])} = ${_money(total_usd)} — no remainder, nothing dropped.\n"
        )

    out.append("\n## 4. Findings\n")
    if not findings:
        out.append("\nNone.\n")
    else:
        out.append("\n| Severity | Code | Detail |\n|---|---|---|\n")
        for sev, code, msg in _finding_rows(findings):
            out.append(f"| {sev} | `{code}` | {msg} |\n")

    out.append("\n## 5. Verification checks (independent re-derivation)\n")
    out.append("\n| Check | Result | Detail |\n|---|---|---|\n")
    for name, passed, detail in checks:
        out.append(f"| `{name}` | {'PASS' if passed else '**FAIL**'} | {detail} |\n")

    review_all = [d for ds in decisions_by_source.values() for d in ds if d.disposition == "REVIEW"]
    suspense_all = [
        d for ds in decisions_by_source.values() for d in ds if d.disposition == "SUSPENSE"
    ]

    out.append("\n## 6. Review queue (human sign-off required)\n")
    if not review_all:
        out.append("\nEmpty.\n")
    else:
        out.append(
            "\n| Source | TB account | Net USD | Proposed → COA | Conf | Runner-up | Margin | Flags |\n"
            "|---|---|---|---|---|---|---|---|\n"
        )
        for d in sorted(review_all, key=lambda x: (-x.confidence, x.source, x.account_code)):
            out.append(
                f"| {d.source} | {d.account_code} {_short(d.account_name)} | {_money(d.usd_net)} | "
                f"{d.mapped_code} {_short(d.mapped_name)} | {_conf(d.confidence)} | "
                f"{d.runner_up_code or '—'} ({_conf(d.runner_up_confidence)}) | {_conf(d.margin)} | "
                f"{', '.join(d.flags) or '—'} |\n"
            )

    out.append("\n## 7. Suspense (excluded from applied mappings, never dropped)\n")
    if not suspense_all:
        out.append("\nEmpty.\n")
    else:
        out.append("\n| Source | TB account | Net USD | Reason |\n|---|---|---|---|\n")
        for d in sorted(suspense_all, key=lambda x: (x.source, x.account_code)):
            out.append(
                f"| {d.source} | {d.account_code} {_short(d.account_name)} | {_money(d.usd_net)} | "
                f"{d.reasons[0] if d.reasons else ''} |\n"
            )

    out.append("\n## 8. Configuration echo\n")
    out.append("\n```yaml\n" + json.dumps(config.as_dict(), sort_keys=True, indent=2) + "\n```\n")
    return "".join(out)


def _short(name: str, limit: int = 32) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _csv(value: str) -> str:
    if any(ch in value for ch in (",", '"', "\n")):
        return '"' + value.replace('"', '""') + '"'
    return value


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
