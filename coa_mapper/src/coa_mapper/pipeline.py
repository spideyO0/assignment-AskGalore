from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .coa import structural_findings
from .config import MapperConfig
from .fx import aggregate_rows, row_translation_table, to_usd
from .gate import decide, synthesize_untranslated
from .io_loaders import load_coa, load_fx, load_tb
from .matcher import Matcher, match_config_from
from .models import Decision, Finding, SourceResult
from .report import (
    render_decisions_jsonl,
    render_mapped_tb,
    render_review_queue,
    render_summary,
    render_suspense,
    render_validation_report,
    sha256_of,
)
from .verifier import verify_from_disk

SOURCE_FILES = {"current": "trial_balance.csv", "prior": "prior_period_tb.csv"}
SHARED_FILES = ["chart_of_accounts.csv", "fx_rates.csv"]

EXIT_CLEAN = 0
EXIT_DISCLOSED = 1
EXIT_HARD = 2


@dataclass
class RunOutcome:
    exit_code: int
    artifacts: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)


def run(config: MapperConfig) -> RunOutcome:
    inputs_dir = config.inputs_dir
    nodes, coa_load_finds = load_coa(inputs_dir / "chart_of_accounts.csv")
    rates, fx_load_finds = load_fx(inputs_dir / "fx_rates.csv")
    all_findings: list[Finding] = coa_load_finds + fx_load_finds + structural_findings(nodes)

    source_results: dict[str, SourceResult] = {}
    per_source_rows: dict[str, list[dict]] = {}
    current_nets: dict[str, Decimal] | None = None

    match_cfg = match_config_from(config)

    for source in config.sources:
        rows, tb_finds = load_tb(inputs_dir / SOURCE_FILES[source], source)
        all_findings.extend(tb_finds)
        aggregates, agg_finds, total_abs, untranslatable = aggregate_rows(source, rows, rates)
        all_findings.extend(agg_finds)

        nets = {a.account_code: a.usd_net for a in aggregates}
        reference = None if source == "current" else current_nets
        matcher = Matcher(nodes, match_cfg, reference_balances=reference)

        # An account with any untranslatable row is dispositioned once, by
        # synthesize_untranslated, which folds in whatever DID translate. Emitting
        # decide() for the partial aggregate as well would give that account two
        # decisions and double-count it against row and USD conservation.
        partial_by_code = {
            a.account_code: a for a in aggregates if a.account_code in untranslatable
        }
        decisions: list[Decision] = []
        for agg in sorted(aggregates, key=lambda a: a.account_code):
            if agg.account_code in untranslatable:
                continue
            decisions.append(decide(agg, matcher, match_cfg, nets))
        decisions.extend(
            synthesize_untranslated(source, rows, untranslatable, partial_by_code).values()
        )
        all_findings.extend(_suspense_rate_findings(source, decisions, config))

        translation = row_translation_table(rows, rates)
        row_records = []
        for row in sorted(rows, key=lambda r: r.line_no):
            rate, origin = translation.get(row.row_id, (None, "UNTRANSLATED"))
            row_records.append(
                {
                    "row_id": row.row_id,
                    "account_code": row.account_code,
                    "account_name": row.account_name,
                    "currency": row.currency,
                    "debit": row.debit,
                    "credit": row.credit,
                    "fx_rate": rate,
                    "rate_origin": origin,
                    "usd_debit": to_usd(row.debit, rate) if rate is not None else Decimal("0.00"),
                    "usd_credit": to_usd(row.credit, rate) if rate is not None else Decimal("0.00"),
                }
            )

        source_results[source] = SourceResult(
            source=source,
            decisions=decisions,
            aggregates=aggregates,
            input_row_count=len(rows),
            input_usd_abs_total=total_abs,
        )
        per_source_rows[source] = row_records
        if source == "current":
            current_nets = nets

    decisions_by_source = {s: r.decisions for s, r in source_results.items()}
    checks_raw, verifier_findings = verify_from_disk(
        inputs_dir, decisions_by_source, config, disclosed_findings=all_findings
    )
    all_findings.extend(verifier_findings)
    checks: list[tuple[str, bool, str]] = [(c.name, c.passed, c.detail) for c in checks_raw]

    all_decisions = [d for ds in decisions_by_source.values() for d in ds]
    data_artifacts_pass1 = _render_data_artifacts(source_results, per_source_rows, all_decisions)
    data_artifacts_pass2 = _render_data_artifacts(source_results, per_source_rows, all_decisions)
    identical = data_artifacts_pass1 == data_artifacts_pass2
    checks.append(
        (
            "artifacts:idempotent_render",
            identical,
            f"data artifacts rendered twice byte-identical={identical} "
            f"files={sorted(data_artifacts_pass1)}",
        )
    )

    input_hashes = {
        name: sha256_of(inputs_dir / name)
        for name in sorted([SOURCE_FILES[s] for s in config.sources] + SHARED_FILES)
    }
    input_row_counts = {}
    for name in input_hashes:
        input_row_counts[name] = (
            len((inputs_dir / name).read_text(encoding="utf-8-sig").splitlines()) - 1
        )

    has_hard_failure = any(f.severity.value == "ERROR" for f in all_findings) or any(
        not p for _, p, _ in checks
    )
    has_disclosed = any(f.severity.value != "ERROR" for f in all_findings) or any(
        d.disposition in ("REVIEW", "SUSPENSE") for d in all_decisions
    )
    if has_hard_failure:
        exit_code = EXIT_HARD
    elif has_disclosed:
        exit_code = EXIT_DISCLOSED
    else:
        exit_code = EXIT_CLEAN

    artifacts = dict(data_artifacts_pass1)
    artifacts["validation_report.md"] = render_validation_report(
        config,
        input_hashes,
        input_row_counts,
        decisions_by_source,
        all_findings,
        checks,
        exit_code,
    )
    artifacts["summary.json"] = render_summary(
        _build_summary(
            input_hashes,
            input_row_counts,
            source_results,
            all_findings,
            checks,
            exit_code,
        )
    )

    return RunOutcome(
        exit_code=exit_code,
        artifacts=artifacts,
        findings=all_findings,
        checks=checks,
        decisions=all_decisions,
    )


def _render_data_artifacts(
    source_results: dict[str, SourceResult],
    per_source_rows: dict[str, list[dict]],
    all_decisions: list[Decision],
) -> dict[str, str]:
    rendered: dict[str, str] = {}
    for source in sorted(source_results):
        decision_by_code = {d.account_code: d for d in source_results[source].decisions}
        rendered[f"mapped_tb_{source}.csv"] = render_mapped_tb(
            per_source_rows[source], decision_by_code
        )
    rendered["review_queue.csv"] = render_review_queue(all_decisions)
    rendered["suspense.csv"] = render_suspense(all_decisions)
    rendered["decisions.jsonl"] = render_decisions_jsonl(all_decisions)
    return rendered


def _build_summary(
    input_hashes: dict[str, str],
    input_row_counts: dict[str, int],
    source_results: dict[str, SourceResult],
    findings: list[Finding],
    checks: list[tuple[str, bool, str]],
    exit_code: int,
) -> dict:
    by_severity = {"ERROR": 0, "WARN": 0, "INFO": 0}
    by_code: dict[str, int] = {}
    for f in findings:
        by_severity[f.severity.value] += 1
        by_code[f.code] = by_code.get(f.code, 0) + 1
    status = {0: "CLEAN_PASS", 1: "PASS_WITH_DISCLOSED_EXCEPTIONS", 2: "HARD_FAILURE"}[exit_code]

    decisions_section: dict[str, dict] = {}
    for source, result in sorted(source_results.items()):
        counts = {"AUTO_APPLIED": 0, "REVIEW": 0, "SUSPENSE": 0}
        usd = {"AUTO_APPLIED": Decimal("0"), "REVIEW": Decimal("0"), "SUSPENSE": Decimal("0")}
        for d in result.decisions:
            counts[d.disposition] += 1
            usd[d.disposition] += abs(d.usd_net)
        decisions_section[source] = {
            "counts": counts,
            "usd_abs_totals": {k: str(v) for k, v in usd.items()},
            "input_rows": result.input_row_count,
        }

    return {
        "run_status": status,
        "exit_code": exit_code,
        "inputs": {
            name: {"sha256": h, "rows": input_row_counts.get(name)}
            for name, h in sorted(input_hashes.items())
        },
        "decisions": decisions_section,
        "findings": {
            "total": len(findings),
            "by_severity": by_severity,
            "by_code": dict(sorted(by_code.items())),
        },
        "verification_checks": [{"name": n, "passed": p, "detail": d} for n, p, d in checks],
    }


def _suspense_rate_findings(
    source: str,
    decisions: list[Decision],
    config: MapperConfig,
) -> list[Finding]:
    """Escalate when suspense stops being an exception and becomes the outcome.

    Exit codes are otherwise presence-based — any suspense row means "disclosed
    exceptions" — so a chart of accounts with no usable targets put every account
    in suspense and still reported a passing run. Nothing was lost, but a total
    mapping collapse must not read as routine review workload.
    """
    if not decisions:
        return []
    susp = [d for d in decisions if d.disposition == "SUSPENSE"]
    if not susp:
        return []

    by_count = len(susp) / len(decisions)
    total_usd = sum((abs(d.usd_net) for d in decisions), Decimal("0"))
    susp_usd = sum((abs(d.usd_net) for d in susp), Decimal("0"))
    by_usd = float(susp_usd / total_usd) if total_usd else 0.0
    limit = config.max_suspense_ratio
    if by_count <= limit and by_usd <= limit:
        return []

    return [
        Finding(
            "SUSPENSE_RATE_EXCEEDED",
            f"{source}: {len(susp)}/{len(decisions)} accounts ({by_count:.1%}) and "
            f"${susp_usd:,.2f} of ${total_usd:,.2f} ({by_usd:.1%}) are in suspense, over the "
            f"{limit:.0%} limit. Nothing was dropped, but at this rate the mapping has "
            f"failed rather than produced exceptions — check the chart of accounts before "
            f"working the queue",
            (f"{source}:suspense_rate",),
        )
    ]


def write_artifacts(artifacts: dict[str, str], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in sorted(artifacts):
        path = output_dir / name
        path.write_text(artifacts[name], encoding="utf-8", newline="")
        written.append(path)
    return written
