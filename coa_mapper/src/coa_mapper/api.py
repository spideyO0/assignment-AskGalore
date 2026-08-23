"""HTTP API for the UI mode.

Deliberately built on the standard library. The pipeline's whole claim is that it
is deterministic, dependency-light and auditable; bolting a web framework onto it
to serve six endpoints would undercut that for no benefit. `rapidfuzz` and
`PyYAML` remain the only runtime dependencies whether you run the CLI or the UI.

The API is a thin shell around exactly the same `run(config)` the CLI calls. It
does not reimplement any policy, does not cache, and holds no state between
requests: uploaded files land in a temp directory, the pipeline runs, artifacts
come back in memory, the directory is destroyed. Two runs of the same inputs
through the UI produce the same bytes as the CLI, which is the point.
"""

from __future__ import annotations

import json
import tempfile
import traceback
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import EntityPolicyError, MapperConfig, apply_entity_policy
from .pipeline import EXIT_HARD, SHARED_FILES, SOURCE_FILES, run

MAX_BODY_BYTES = 32 * 1024 * 1024
REQUIRED = [*SHARED_FILES, SOURCE_FILES["current"]]
OPTIONAL = [SOURCE_FILES["prior"], "manual_adjustments.json"]
STATUS_TEXT = {0: "CLEAN PASS", 1: "PASS WITH DISCLOSED EXCEPTIONS", 2: "HARD FAILURE"}


def _bundled_inputs() -> Path:
    return Path(__file__).resolve().parents[3] / "inputs"


def execute(files: dict[str, str], entity: str | None, base: MapperConfig) -> dict[str, Any]:
    """Run the pipeline over an in-memory set of input files."""
    missing = [n for n in REQUIRED if n not in files]
    if missing:
        return {
            "ok": False,
            "exit_code": EXIT_HARD,
            "status": STATUS_TEXT[EXIT_HARD],
            "error": f"missing required input file(s): {', '.join(missing)}",
            "required": REQUIRED,
            "optional": OPTIONAL,
        }

    with tempfile.TemporaryDirectory(prefix="coa-mapper-") as tmp:
        tmp_path = Path(tmp)
        for name, content in files.items():
            if name in REQUIRED or name in OPTIONAL:
                (tmp_path / name).write_text(content, encoding="utf-8")

        # A prior-period TB is optional over the API: without it the continuity
        # feature has nothing to compare against, which the pipeline already
        # handles by renormalizing the weights. Silently pretending the file
        # exists would be worse than running one source and saying so.
        sources = ("current", "prior") if SOURCE_FILES["prior"] in files else ("current",)
        config = replace(base, inputs_dir=tmp_path, sources=sources)
        if entity:
            try:
                config = apply_entity_policy(config, entity)
            except EntityPolicyError as exc:
                return {
                    "ok": False,
                    "exit_code": EXIT_HARD,
                    "status": STATUS_TEXT[EXIT_HARD],
                    "error": str(exc),
                }

        try:
            outcome = run(config)
        except Exception as exc:  # noqa: BLE001 - mirrors the CLI's exit contract
            return {
                "ok": False,
                "exit_code": EXIT_HARD,
                "status": STATUS_TEXT[EXIT_HARD],
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=6),
            }

    decisions = [
        json.loads(line) for line in outcome.artifacts["decisions.jsonl"].splitlines() if line
    ]
    return {
        "ok": True,
        "exit_code": outcome.exit_code,
        "status": STATUS_TEXT[outcome.exit_code],
        "sources": list(sources),
        "entity": config.entity or None,
        "entity_name": config.entity_name or None,
        "config": config.as_dict(),
        "summary": json.loads(outcome.artifacts["summary.json"]),
        "decisions": decisions,
        "findings": [
            {
                "severity": f.severity.value,
                "code": f.code,
                "message": f.message,
                "refs": list(f.refs),
            }
            for f in sorted(outcome.findings, key=lambda f: f.sort_key())
        ],
        "checks": [{"name": n, "passed": p, "detail": d} for n, p, d in outcome.checks],
        "artifacts": dict(outcome.artifacts),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "coa-mapper"
    base_config: MapperConfig = MapperConfig()

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"  api {fmt % args}")

    # ------------------------------------------------------------------ utils
    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ verbs
    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self._send(200, {"ok": True, "service": "coa-mapper"})
        elif self.path == "/api/sample":
            root = _bundled_inputs()
            if not root.exists():
                self._send(404, {"ok": False, "error": f"no bundled inputs at {root}"})
                return
            files = {
                n: (root / n).read_text(encoding="utf-8-sig")
                for n in [*REQUIRED, *OPTIONAL]
                if (root / n).exists()
            }
            self._send(200, {"ok": True, "files": files})
        elif self.path == "/api/entities":
            d = self.base_config.entities_dir
            names = (
                sorted(p.stem for p in d.glob("*.yaml") if not p.stem.startswith("_"))
                if d.exists()
                else []
            )
            self._send(200, {"ok": True, "entities": names})
        else:
            self._send(404, {"ok": False, "error": f"no route {self.path}"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/run":
            self._send(404, {"ok": False, "error": f"no route {self.path}"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send(413, {"ok": False, "error": f"body must be 1..{MAX_BODY_BYTES} bytes"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            self._send(400, {"ok": False, "error": f"malformed JSON body: {exc}"})
            return

        files = payload.get("files")
        if not isinstance(files, dict) or not files:
            self._send(400, {"ok": False, "error": 'expected {"files": {name: content}}'})
            return

        result = execute(
            {str(k): str(v) for k, v in files.items()},
            payload.get("entity") or None,
            self.base_config,
        )
        # A pipeline that ran and reported a hard failure is a successful HTTP
        # exchange reporting a bad run: the exit code is the payload, not the
        # transport. Only a malformed request is a 4xx.
        self._send(200 if result.get("ok") or "exit_code" in result else 500, result)


def serve(host: str = "127.0.0.1", port: int = 8765, config: MapperConfig | None = None) -> int:
    Handler.base_config = config or MapperConfig()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"coa-mapper API listening on http://{host}:{port}")
    print("  GET  /api/health    GET /api/sample    GET /api/entities    POST /api/run")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()
    return 0
