from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .config import MapperConfig
from .fx import aggregate_rows
from .io_loaders import load_coa, load_fx, load_tb
from .matcher import Matcher, match_config_from
from .models import Decision, Finding


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def _source_filename(source: str) -> str:
    return "trial_balance.csv" if source == "current" else f"{source}_period_tb.csv"


def verify_from_disk(
    inputs_dir: Path,
    decisions_by_source: dict[str, list[Decision]],
    config: MapperConfig,
    disclosed_findings: list[Finding] | None = None,
) -> tuple[list[CheckResult], list[Finding]]:
    checks: list[CheckResult] = []
    findings: list[Finding] = []

    nodes, coa_finds = load_coa(inputs_dir / "chart_of_accounts.csv")
    findings.extend(coa_finds)
    rates, fx_loads = load_fx(inputs_dir / "fx_rates.csv")
    del fx_loads

    auto_min = Decimal(str(config.auto_min))
    current_rows, _ = load_tb(inputs_dir / "trial_balance.csv", "current")
    current_aggs, _, _, _ = aggregate_rows("current", current_rows, rates)
    reference = {a.account_code: a.usd_net for a in current_aggs}

    for source in sorted(decisions_by_source):
        rows, load_finds = load_tb(inputs_dir / _source_filename(source), source)
        findings.extend(load_finds)
        if not rows:
            checks.append(CheckResult(f"{source}:rows_loaded", False, "no rows loaded"))
            continue

        aggregates, _, total_abs, untranslatable = aggregate_rows(source, rows, rates)
        agg_by_code = {a.account_code: a for a in aggregates}
        source_balances = {a.account_code: a.usd_net for a in aggregates}
        ref_for_source = None if source == "current" else reference

        from .gate import synthesize_untranslated

        synth = synthesize_untranslated(
            source,
            rows,
            untranslatable,
            {c: a for c, a in agg_by_code.items() if c in untranslatable},
        )
        # `claimed` is the pipeline's own output and nothing else. It used to be
        # overwritten with the verifier's re-derived stubs, which meant
        # usd_conservation compared the re-derivation against itself — a wrong
        # usd_net in the artifact could not fail the check. Comparing the claimed
        # figures against an independently computed total is the whole point.
        claimed = {d.account_code: d for d in decisions_by_source[source]}
        partition_rows: set[str] = set()
        overlaps: set[str] = set()
        for dec in claimed.values():
            for rid in dec.row_ids:
                if rid in partition_rows:
                    overlaps.add(rid)
                partition_rows.add(rid)
        all_row_ids = {r.row_id for r in rows}
        missing = all_row_ids - partition_rows
        extra = partition_rows - all_row_ids
        checks.append(
            CheckResult(
                f"{source}:row_conservation",
                not missing and not extra and not overlaps,
                f"input_rows={len(all_row_ids)} covered={len(partition_rows)} "
                f"missing={sorted(missing)[:5]} extra={sorted(extra)[:5]} "
                f"overlaps={sorted(overlaps)[:5]}",
            )
        )

        usd_abs = sum((abs(d.usd_net) for d in claimed.values()), Decimal("0"))
        checks.append(
            CheckResult(
                f"{source}:usd_conservation",
                usd_abs == total_abs,
                f"|sum(nets)|={total_abs} sum(|decision nets|)={usd_abs}",
            )
        )

        from .gate import decide

        verifier_match_cfg = match_config_from(config)
        redecided = {}
        for code in sorted(agg_by_code):
            if code in untranslatable:
                continue  # mirrors the pipeline: synth owns these accounts
            redecided[code] = decide(
                agg_by_code[code],
                Matcher(nodes, verifier_match_cfg, reference_balances=ref_for_source),
                verifier_match_cfg,
                source_balances=source_balances,
            )
        redecided.update(synth)

        diverged = [
            code
            for code in sorted(set(claimed) | set(redecided))
            if code not in claimed
            or code not in redecided
            or claimed[code].disposition != redecided[code].disposition
            or claimed[code].confidence != redecided[code].confidence
            or claimed[code].mapped_code != redecided[code].mapped_code
        ]
        checks.append(
            CheckResult(
                f"{source}:decision_reproduction",
                not diverged,
                f"independently re-derived {len(redecided)} account decisions; diverged={diverged[:5]}",
            )
        )

        bad_auto = [
            code
            for code, dec in claimed.items()
            if dec.disposition == "AUTO_APPLIED"
            and (
                not dec.mapped_code
                or (dec.tier == "FUZZY_COMPOSITE" and dec.confidence < auto_min)
                or set(dec.flags) & {"NORMAL_BALANCE_VETO", "AMBIGUOUS_TIE"}
            )
        ]
        auto_count = sum(1 for d in claimed.values() if d.disposition == "AUTO_APPLIED")
        checks.append(
            CheckResult(
                f"{source}:auto_gate_integrity",
                not bad_auto,
                f"AUTO_APPLIED={auto_count} threshold_violations={bad_auto[:5]}",
            )
        )

        invalid = [
            code
            for code, dec in claimed.items()
            if dec.disposition not in ("AUTO_APPLIED", "REVIEW", "SUSPENSE") or not dec.reasons
        ]
        checks.append(
            CheckResult(
                f"{source}:dispositions_total",
                not invalid,
                f"accounts={len(claimed)} every disposition valid with reasons; invalid={invalid[:5]}",
            )
        )

        fallback_currencies_used: set[str] = set()
        untranslated_ok = True
        for agg in aggregates:
            for currency, origin in agg.rate_by_row:
                if origin == "period_average_fallback":
                    fallback_currencies_used.add(currency)
        for code in sorted(untranslatable):
            dec_or_none = claimed.get(code)
            if (
                dec_or_none is None
                or dec_or_none.disposition != "SUSPENSE"
                or "NO_FX_RATE" not in dec_or_none.flags
            ):
                untranslated_ok = False

        disclosed_fallbacks: set[str] = set()
        if disclosed_findings:
            for f in disclosed_findings:
                if f.code == "FX_PERIOD_END_FALLBACK" and "currency " in f.message:
                    disclosed_fallbacks.add(f.message.split("currency ", 1)[1].split(":", 1)[0])

        checks.append(
            CheckResult(
                f"{source}:fx_fallbacks_flagged",
                fallback_currencies_used <= disclosed_fallbacks and untranslated_ok,
                f"independently recomputed fallbacks={sorted(fallback_currencies_used)} "
                f"disclosed_in_findings={sorted(disclosed_fallbacks)} "
                f"untranslatable_routed_to_suspense={untranslatable and untranslated_ok}",
            )
        )

    return checks, findings
