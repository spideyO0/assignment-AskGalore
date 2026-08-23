from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import EntityPolicyError, apply_entity_policy, load_config
from .pipeline import EXIT_HARD, run, write_artifacts

STATUS_TEXT = {
    0: "CLEAN PASS",
    1: "PASS WITH DISCLOSED EXCEPTIONS",
    2: "HARD FAILURE",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="coa-mapper",
        description="Deterministic TB-to-COA mapper with confidence gating and audit trail",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run the mapping pipeline")
    run_p.add_argument("--config", type=Path, default=None, help="YAML config path")
    run_p.add_argument("--inputs", type=Path, default=None, help="input data directory")
    run_p.add_argument("--out", type=Path, default=None, help="output directory")
    run_p.add_argument(
        "--entity",
        default=None,
        help="per-entity policy from config/entities/<name>.yaml, layered over the base config",
    )

    serve_p = sub.add_parser("serve", help="run the HTTP API that backs the UI")
    serve_p.add_argument("--config", type=Path, default=None, help="YAML config path")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)

    if args.command == "serve":
        from .api import serve

        return serve(args.host, args.port, load_config(args.config))

    config = load_config(args.config)
    if args.entity:
        try:
            config = apply_entity_policy(config, args.entity)
        except EntityPolicyError as exc:
            print(f"status: {STATUS_TEXT[EXIT_HARD]} (exit {EXIT_HARD})", file=sys.stderr)
            print(f"  {exc}", file=sys.stderr)
            return EXIT_HARD
    if args.inputs is not None:
        config = _with_overrides(config, inputs_dir=args.inputs)
    if args.out is not None:
        config = _with_overrides(config, output_dir=args.out)

    # Anything that stops the run from completing is a HARD FAILURE (exit 2).
    # Without this, an unreadable or malformed input escaped as an uncaught
    # exception and Python exited 1 — the code that means "PASS WITH DISCLOSED
    # EXCEPTIONS". A CI wired "fail on 2, review on 1" then read a missing trial
    # balance as a successful run needing review. Failures must never exit 1.
    try:
        outcome = run(config)
        written = write_artifacts(outcome.artifacts, config.output_dir)
    except Exception as exc:  # noqa: BLE001 - the exit contract is the point
        print(f"status: {STATUS_TEXT[EXIT_HARD]} (exit {EXIT_HARD})", file=sys.stderr)
        print(f"  {type(exc).__name__}: {exc}", file=sys.stderr)
        print("  no artifacts written; inputs could not be processed", file=sys.stderr)
        return EXIT_HARD

    print(f"status: {STATUS_TEXT[outcome.exit_code]} (exit {outcome.exit_code})")
    for source in sorted({d.source for d in outcome.decisions}):
        ds = [d for d in outcome.decisions if d.source == source]
        auto = sum(1 for d in ds if d.disposition == "AUTO_APPLIED")
        review = sum(1 for d in ds if d.disposition == "REVIEW")
        susp = sum(1 for d in ds if d.disposition == "SUSPENSE")
        print(f"  {source}: auto={auto} review={review} suspense={susp} total={len(ds)}")
    failed = [name for name, passed, _ in outcome.checks if not passed]
    if failed:
        print(f"  FAILED CHECKS: {failed}")
    errors = [f for f in outcome.findings if f.severity.value == "ERROR"]
    warns = [f for f in outcome.findings if f.severity.value == "WARN"]
    print(f"  findings: errors={len(errors)} warnings={len(warns)}")
    print(f"  artifacts: {len(written)} files in {config.output_dir}/")
    return outcome.exit_code


def _with_overrides(config, inputs_dir: Path | None = None, output_dir: Path | None = None):
    from dataclasses import replace

    return replace(
        config,
        inputs_dir=inputs_dir if inputs_dir is not None else config.inputs_dir,
        output_dir=output_dir if output_dir is not None else config.output_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
