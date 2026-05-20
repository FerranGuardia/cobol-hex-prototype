"""F5 — the conveyor belt.

ONE persona writes Java. The harness gates check it sequentially:

    code-arrived  →  compile  →  drift  →  run  →  oracle-diff

If any gate fails, the persona is re-called with the gate's feedback
appended to the prompt. Up to MAX_TOTAL_RETRIES total re-calls across all
gates. If we exhaust retries, the pipeline HARD FAILS visibly — no silent
pass, no "well the contract validated" excuse. The only outputs are:

  (a) a fully validated Java tree that compiles, passes hex/OTel rules,
      runs against the fixture, and matches expected-output.txt; or
  (b) a `gate_failure.json` artifact naming the gate that blocked + the
      feedback that was being fed back when retries ran out.

No parallel personas. No LLM contract-diff. No "two LLMs auditing each
other." Just generation + deterministic gates + retry-with-feedback.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.coordinator import Coordinator
from app.core.schemas import RunConfig
from harness.gates import (
    GateResult,
    gate_code_arrived,
    gate_compile,
    gate_drift,
    gate_oracle_diff,
    gate_run,
)

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
CODE_AUTHOR_PROMPT = PROMPTS_DIR / "code-author.md"

JAVA_BLOCK = re.compile(
    r"```java\s+//\s*(?P<path>[^\n]+)\n(?P<body>.*?)```",
    re.DOTALL,
)

MAX_TOTAL_RETRIES = 6   # global cap across all gates for one slice
Mode = Literal["conveyor-belt"]  # legacy "single-pass" / "two-pass-blind" removed


@dataclass
class GateLogEntry:
    attempt: int            # 1-indexed attempt number
    gate: str               # gate name (code-arrived, compile, drift, run, oracle-diff)
    ok: bool
    elapsed: float
    detail_summary: str     # short human-readable detail


@dataclass
class ConveyorResult:
    run_id: str
    shipped: bool
    final_gate: str | None   # which gate the pipeline ended on (passed it, or blocked there)
    attempts: int
    log: list[GateLogEntry] = field(default_factory=list)
    raw_responses: list[dict[str, Any]] = field(default_factory=list)
    last_gate_feedback: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "shipped": self.shipped,
            "final_gate": self.final_gate,
            "attempts": self.attempts,
            "log": [
                {
                    "attempt": e.attempt,
                    "gate": e.gate,
                    "ok": e.ok,
                    "elapsed": e.elapsed,
                    "detail": e.detail_summary,
                }
                for e in self.log
            ],
            "last_gate_feedback": self.last_gate_feedback,
        }


# ----------------------------------------------------------------------------

def run(
    cfg: RunConfig,
    run_id: str,
    source_file: Path,
    *,
    force: bool = False,
    k: int = 1,                           # accepted for back-compat; ignored in conveyor mode
    mode: Mode = "conveyor-belt",          # accepted for back-compat; only mode now
) -> Path:
    """F5 conveyor belt entry. Returns the output dir."""
    del k, mode  # ignored — there is only one mode
    coord = Coordinator(cfg)

    context_pack_path = cfg.artifacts_dir / run_id / "context_pack.md"
    if not context_pack_path.exists():
        raise FileNotFoundError(
            f"context_pack.md missing; run `app context-pack --file {source_file}` first"
        )
    context = context_pack_path.read_text()
    artifacts_root = cfg.artifacts_dir / run_id
    output_root = artifacts_root / "output"
    classes_out = artifacts_root / "classes"
    raw_dir = artifacts_root / "raw" / "code-author"
    raw_dir.mkdir(parents=True, exist_ok=True)

    base_prompt = CODE_AUTHOR_PROMPT.read_text()

    slice_name = source_file.stem.upper()
    repo_root = Path(__file__).resolve().parents[3]
    vendor_dir = repo_root / "vendor" / "jars"
    fixture_path = _resolve_fixture(repo_root, slice_name)
    expected_path = repo_root / "golden-outputs" / f"{slice_name}.expected-output.txt"

    result = ConveyorResult(run_id=run_id, shipped=False, final_gate=None, attempts=0)
    accumulated_feedback = ""

    for attempt in range(1, MAX_TOTAL_RETRIES + 2):  # +1 because attempt 1 is the initial call
        result.attempts = attempt

        # Compose the prompt for this attempt: base + accumulated feedback.
        prompt = base_prompt
        if accumulated_feedback:
            prompt = (
                base_prompt
                + "\n\n---\n\n## Retry feedback from the harness\n\n"
                + "Your previous emission did not pass a deterministic gate. The harness "
                + "fed back the exact failure below. Fix it in this next emission. Do not "
                + "explain — just emit corrected Java. Do not regress on previously-passing gates.\n\n"
                + accumulated_feedback
            )

        # Persona call.
        raw_response = coord.call_codex(
            prompt=prompt, context=context, force=(force or attempt > 1),
        )
        (raw_dir / f"response-{attempt - 1}.json").write_text(
            json.dumps(raw_response, indent=2, default=str)
        )
        result.raw_responses.append(raw_response)

        # Parse + write Java files to disk.
        final_message = str(raw_response.get("final_message") or raw_response.get("stdout") or "")
        files = _parse_response(final_message)
        _wipe_and_save_java(output_root, files)

        # Backcompat: still write codex_response.json at the root for UI / older tooling.
        if attempt == 1 or result.shipped:
            (artifacts_root / "codex_response.json").write_text(
                json.dumps(raw_response, indent=2, default=str)
            )

        # GATE 1 — code arrived.
        g = gate_code_arrived(output_root, slice_name=slice_name)
        _log_gate(result, attempt, g)
        if not g.ok:
            accumulated_feedback = g.feedback
            if attempt > MAX_TOTAL_RETRIES:
                result.final_gate = "code-arrived"
                result.last_gate_feedback = g.feedback
                break
            continue

        # GATE 2 — compile.
        g = gate_compile(output_root, vendor_dir=vendor_dir, classes_out=classes_out)
        _log_gate(result, attempt, g)
        if not g.ok:
            accumulated_feedback = g.feedback
            if attempt > MAX_TOTAL_RETRIES:
                result.final_gate = "compile"
                result.last_gate_feedback = g.feedback
                break
            continue

        # GATE 3 — drift.
        g = gate_drift(output_root, cobol_source=source_file)
        _log_gate(result, attempt, g)
        if not g.ok:
            accumulated_feedback = g.feedback
            if attempt > MAX_TOTAL_RETRIES:
                result.final_gate = "drift"
                result.last_gate_feedback = g.feedback
                break
            continue

        # GATE 4 — run program.
        g = gate_run(
            output_root,
            classes_out=classes_out,
            vendor_dir=vendor_dir,
            fixture_path=fixture_path,
            slice_name=slice_name,
        )
        _log_gate(result, attempt, g)
        if not g.ok:
            accumulated_feedback = g.feedback
            if attempt > MAX_TOTAL_RETRIES:
                result.final_gate = "run"
                result.last_gate_feedback = g.feedback
                break
            continue
        captured_stdout = g.detail.get("stdout", "")

        # GATE 5 — oracle diff.
        g = gate_oracle_diff(captured_stdout, expected_path=expected_path, slice_name=slice_name)
        _log_gate(result, attempt, g)
        if not g.ok:
            accumulated_feedback = g.feedback
            if attempt > MAX_TOTAL_RETRIES:
                result.final_gate = "oracle-diff"
                result.last_gate_feedback = g.feedback
                break
            continue

        # All five gates passed — ship it.
        result.shipped = True
        result.final_gate = "oracle-diff"  # last gate cleared
        break

    # Persist the conveyor log + last feedback.
    (artifacts_root / "conveyor.json").write_text(json.dumps(result.to_dict(), indent=2))
    if not result.shipped:
        (artifacts_root / "gate_failure.json").write_text(json.dumps({
            "run_id": run_id,
            "blocked_at": result.final_gate,
            "attempts": result.attempts,
            "last_feedback": result.last_gate_feedback,
        }, indent=2))

    return output_root


# ----------------------------------------------------------------------------

def _wipe_and_save_java(output_root: Path, files: dict[str, str]) -> None:
    """Erase prior Java + write fresh emission. Forces clean retries."""
    if output_root.exists():
        for p in output_root.rglob("*.java"):
            try:
                p.unlink()
            except OSError:
                pass
    for relpath, body in files.items():
        target = output_root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)


def _parse_response(text: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for m in JAVA_BLOCK.finditer(text):
        files[m.group("path").strip()] = m.group("body")
    return files


def _log_gate(result: ConveyorResult, attempt: int, gate: GateResult) -> None:
    detail = ""
    if gate.name == "code-arrived":
        detail = f"{gate.detail.get('files_found', 0)} files"
    elif gate.name == "compile":
        if gate.ok:
            detail = f"{gate.detail.get('class_files', 0)} class files"
        else:
            detail = "javac errors"
    elif gate.name == "drift":
        if gate.ok:
            detail = "0 findings"
        else:
            detail = f"{gate.detail.get('fails', 0)} fails / {gate.detail.get('warns', 0)} warns"
    elif gate.name == "run":
        if gate.ok:
            detail = f"rc=0, stdout {gate.detail.get('stdout_bytes', 0)}B"
        else:
            detail = f"rc={gate.detail.get('returncode', '?')}"
    elif gate.name == "oracle-diff":
        if gate.ok:
            detail = "matches"
        else:
            detail = f"{gate.detail.get('diff_lines', 0)} diff lines"
    result.log.append(GateLogEntry(
        attempt=attempt, gate=gate.name, ok=gate.ok,
        elapsed=gate.elapsed_seconds, detail_summary=detail,
    ))


def _resolve_fixture(repo_root: Path, slice_name: str) -> Path:
    """Find the canonical fixture for a slice. Defaults to CardDemo carddata.txt."""
    # The iria contract names the ASCII path; for v1 we hard-code the known CardDemo location.
    candidate = repo_root.parent / "CardDemo" / "app" / "data" / "ASCII" / "carddata.txt"
    if candidate.exists():
        return candidate
    return repo_root / "corpus" / "carddata.txt"  # fallback; non-existent = harness setup error
