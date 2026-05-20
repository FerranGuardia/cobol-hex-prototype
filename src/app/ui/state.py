"""Scan `artifacts/` and report current pipeline state.

Pure read-only. No caching beyond a single call's data. Cheap enough to
poll every 2-3 seconds against a local filesystem.

The model:
- A `Run` is one subdirectory under `artifacts/` whose name matches the
  `YYYYMMDD-HHMMSS-<hash>` shape from `Coordinator.new_run_id`. Smoke runs
  (`f3-iria-smoke`, etc.) are also surfaced but tagged separately.
- Each run has a list of `Phase` records (F3, F4, F5 code-author, F5
  test-author, F5 diff, F6 validate, drift-check). Status = done / running
  / pending, with mtime + size.
- Status `running` is inferred — a phase is "running" if the previous
  phase is done but this one isn't, AND the run's most recent mtime is
  within `LIVE_WINDOW_SECONDS` (so we don't show stale half-finished runs
  as live forever).
- Issues are pulled from validation.json, drift.json, contracts/diff.json,
  and the contract files themselves (schema-valid flag).
- Time-left estimate per in-flight run uses the median wall-clock of the
  last 5 completed runs of the same slice.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LIVE_WINDOW_SECONDS = 15 * 60  # a run is "in flight" only if mtime within this
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]+$")
SMOKE_PREFIX_RE = re.compile(r"^(smoke|f3-|.*-smoke$)")

# Phase definitions. Pre-conveyor phases stay file-based.
PHASES = [
    {"id": "F3", "label": "context pack",  "path": "context_pack.md",     "kind": "file"},
    {"id": "F4", "label": "golden master", "path": "golden_master.json",  "kind": "file"},
]

# Conveyor-belt gates, surfaced from `conveyor.json`. Order matches pipeline/convert.py.
CONVEYOR_GATES = [
    ("code-arrived", "code arrived"),
    ("compile",      "compile (javac)"),
    ("drift",        "drift checks"),
    ("run",          "run vs fixture"),
    ("oracle-diff",  "stdout vs oracle"),
]


@dataclass
class Phase:
    id: str
    label: str
    status: str   # "done" | "running" | "pending"
    mtime: float | None
    size: int | None
    relpath: str
    detail: str = ""


@dataclass
class Issue:
    severity: str   # "error" | "warn" | "info"
    tag: str
    message: str


@dataclass
class Run:
    run_id: str
    kind: str       # "real" | "smoke"
    slice: str | None
    started_at: float | None
    last_mtime: float
    elapsed_seconds: float
    is_live: bool
    overall_status: str    # "running" | "ok" | "issues" | "blocked"
    phases: list[Phase]
    issues: list[Issue] = field(default_factory=list)
    estimated_remaining_seconds: float | None = None
    summary_line: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "slice": self.slice,
            "started_at": self.started_at,
            "last_mtime": self.last_mtime,
            "elapsed_seconds": self.elapsed_seconds,
            "is_live": self.is_live,
            "overall_status": self.overall_status,
            "phases": [p.__dict__ for p in self.phases],
            "issues": [i.__dict__ for i in self.issues],
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
            "summary_line": self.summary_line,
        }


# ---- top-level entry --------------------------------------------------------

def collect(artifacts_root: Path) -> dict[str, Any]:
    """Return the full UI state as a JSON-serializable dict."""
    if not artifacts_root.exists():
        return {
            "generated_at": time.time(),
            "artifacts_root": str(artifacts_root),
            "live": [],
            "recent": [],
            "open_issues": [],
            "history_by_slice": {},
        }

    runs: list[Run] = []
    for d in sorted(artifacts_root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        run = _scan_run(d)
        if run is not None:
            runs.append(run)

    # Build per-slice timing history from completed real runs (used for ETA).
    history_by_slice = _build_history(runs)

    # Compute ETA per live run.
    for run in runs:
        if run.is_live:
            run.estimated_remaining_seconds = _estimate_remaining(run, history_by_slice)

    live = [r for r in runs if r.is_live]
    not_live = [r for r in runs if not r.is_live]

    # Featured run priority: live > shipped/blocked (real conveyor runs) > legacy > smoke.
    def feature_priority(r: Run) -> int:
        if r.is_live:                     return 0
        if r.overall_status in ("shipped", "blocked"): return 1
        if r.overall_status == "legacy":  return 2
        return 3  # smoke
    sorted_for_feature = sorted(
        runs, key=lambda r: (feature_priority(r), -r.last_mtime)
    )
    featured = sorted_for_feature[0] if sorted_for_feature else None
    # Build "recent" list: most-recent-first, excluding the featured run.
    recent_pool = [r for r in not_live if not featured or r.run_id != featured.run_id][:8]

    # Open issues: only from non-live runs that actually have something to report.
    open_issues = [
        {"run_id": r.run_id, "slice": r.slice, **i.__dict__}
        for r in runs[:6]
        for i in r.issues
    ]

    return {
        "generated_at": time.time(),
        "artifacts_root": str(artifacts_root),
        "live": [r.to_dict() for r in live],
        "featured": featured.to_dict() if featured else None,
        "recent": [r.to_dict() for r in recent_pool],
        "open_issues": open_issues,
        "history_by_slice": history_by_slice,
    }


# ---- per-run scanning -------------------------------------------------------

def _scan_run(run_dir: Path) -> Run | None:
    run_id = run_dir.name
    is_smoke = bool(SMOKE_PREFIX_RE.match(run_id)) or not RUN_ID_RE.match(run_id)
    kind = "smoke" if is_smoke else "real"

    # Slice detection: prefer validation.json source_file, fall back to context_pack header.
    slice_name = _detect_slice(run_dir)

    phases: list[Phase] = []
    for p in PHASES:
        path = run_dir / p["path"]
        if path.exists():
            stat = path.stat()
            phases.append(Phase(
                id=p["id"], label=p["label"], status="done",
                mtime=stat.st_mtime, size=stat.st_size, relpath=p["path"],
                detail=_phase_detail(p["id"], path),
            ))
        else:
            phases.append(Phase(
                id=p["id"], label=p["label"], status="pending",
                mtime=None, size=None, relpath=p["path"],
            ))

    # Conveyor-belt gates: derive from conveyor.json if present.
    conveyor_path = run_dir / "conveyor.json"
    if conveyor_path.exists():
        try:
            conveyor = json.loads(conveyor_path.read_text())
            phases.extend(_conveyor_phases(conveyor, conveyor_path))
        except Exception:
            pass
    else:
        # No conveyor.json yet — show gate placeholders if a code-author response landed.
        if (run_dir / "raw" / "code-author").exists():
            for gate_id, label in CONVEYOR_GATES:
                phases.append(Phase(
                    id=f"G:{gate_id}", label=label,
                    status="pending", mtime=None, size=None, relpath="conveyor.json",
                ))

    # Compute run-level mtime + start.
    mtimes = [ph.mtime for ph in phases if ph.mtime is not None]
    last_mtime = max(mtimes) if mtimes else run_dir.stat().st_mtime
    started_at = min(mtimes) if mtimes else None
    elapsed = (last_mtime - started_at) if started_at else 0.0

    # In-flight detection: at least one phase pending, last_mtime recent.
    now = time.time()
    pending = [ph for ph in phases if ph.status == "pending"]
    is_live = bool(pending) and (now - last_mtime) < LIVE_WINDOW_SECONDS and not is_smoke

    # Mark the first pending phase as "running" if live.
    if is_live and pending:
        # The first pending phase that's "next" given done dependencies is running.
        # Simplification: the first pending is the running one.
        running_phase = pending[0]
        running_phase.status = "running"

    # Smoke runs only have F3; trim phase list for clarity.
    if is_smoke:
        phases = [ph for ph in phases if ph.id == "F3"]

    issues = _collect_issues(run_dir, phases)
    conveyor_state = _read_conveyor_state(run_dir)
    overall = _overall_status(is_live, phases, issues, conveyor_state)
    summary = _summary_line(phases, issues, overall, conveyor_state)

    return Run(
        run_id=run_id, kind=kind, slice=slice_name,
        started_at=started_at, last_mtime=last_mtime, elapsed_seconds=elapsed,
        is_live=is_live, overall_status=overall,
        phases=phases, issues=issues, summary_line=summary,
    )


def _conveyor_phases(conveyor: dict, source_path: Path) -> list[Phase]:
    """Turn a conveyor.json into a list of phases (one per gate, plus an attempt counter).

    For each canonical gate, walk the log and take the most recent entry for that gate.
    `ok=True` → done; `ok=False` → blocked/running depending on whether shipped.
    """
    log = conveyor.get("log", [])
    shipped = conveyor.get("shipped", False)
    final_gate = conveyor.get("final_gate")
    attempts = conveyor.get("attempts", 0)
    mtime = source_path.stat().st_mtime if source_path.exists() else None

    # Map gate -> most recent log entry (later attempts override earlier).
    latest: dict[str, dict] = {}
    for entry in log:
        latest[entry.get("gate", "?")] = entry

    out: list[Phase] = []
    if attempts:
        out.append(Phase(
            id="G:attempts", label="conveyor attempts",
            status="done", mtime=mtime, size=None, relpath="conveyor.json",
            detail=f"{attempts} attempt(s) · {'shipped' if shipped else 'blocked at ' + (final_gate or '?')}",
        ))

    for gate_id, label in CONVEYOR_GATES:
        entry = latest.get(gate_id)
        if entry is None:
            status = "pending"
            detail = ""
        elif entry.get("ok"):
            status = "done"
            detail = entry.get("detail") or ""
        else:
            # Failed entry — if pipeline shipped, this gate was eventually passed (skip the
            # historical fail); if not shipped and this is the final gate, mark blocked.
            if shipped:
                status = "done"
                detail = entry.get("detail") or ""
            elif final_gate == gate_id:
                status = "fail"
                detail = entry.get("detail") or ""
            else:
                status = "done"  # passed eventually since we moved past it
                detail = entry.get("detail") or ""
        out.append(Phase(
            id=f"G:{gate_id}", label=label,
            status=status, mtime=mtime, size=None, relpath="conveyor.json",
            detail=detail,
        ))
    return out


def _detect_slice(run_dir: Path) -> str | None:
    val = run_dir / "validation.json"
    if val.exists():
        try:
            data = json.loads(val.read_text())
            src = data.get("source_file") or ""
            if src:
                return Path(src).stem.upper()
        except Exception:
            pass
    ctx = run_dir / "context_pack.md"
    if ctx.exists():
        try:
            first = ctx.read_text(errors="replace").splitlines()[0]
            m = re.search(r"#\s*Context Pack\s*—\s*(\S+?)\.cbl", first)
            if m:
                return m.group(1).upper()
        except Exception:
            pass
    return None


def _phase_detail(phase_id: str, path: Path) -> str:
    """Short human-readable detail line — counts, sizes, headline numbers."""
    try:
        if phase_id == "F3":
            return f"{path.stat().st_size // 1024} KB"
        if phase_id == "F4":
            data = json.loads(path.read_text())
            return f"{len(data.get('assertions', []))} assertions"
        if phase_id == "F5a" or phase_id == "F5b":
            data = json.loads(path.read_text())
            final = data.get("final_message") or ""
            java = final.count("```java")
            jsonb = final.count("```json")
            return f"{java} java · {jsonb} json"
        if phase_id == "F5d":
            data = json.loads(path.read_text())
            s = data.get("summary") or {}
            crit = s.get("critical", 0)
            mat = s.get("material", 0)
            return f"{crit} crit · {mat} material" if (crit or mat) else "ok"
        if phase_id == "F6":
            data = json.loads(path.read_text())
            tags = []
            for t in ("t1", "t2", "t3", "t4"):
                tier = data.get(t) or {}
                if tier.get("status") not in ("pass", "skip"):
                    tags.extend(tier.get("failure_tags") or [])
            return ", ".join(tags) if tags else "all pass"
        if phase_id == "F6d":
            data = json.loads(path.read_text())
            n = len(data.get("findings") or [])
            return "ok" if data.get("ok") else f"{n} findings"
    except Exception as e:
        return f"err: {e.__class__.__name__}"
    return ""


def _collect_issues(run_dir: Path, phases: list[Phase]) -> list[Issue]:
    """Issues come from the conveyor — and only when the conveyor BLOCKED.

    A shipped run has no issues, by definition. We deliberately ignore the
    legacy validation.json / drift.json / contracts/diff.json artifacts; the
    conveyor's gate log is the only source of truth.
    """
    out: list[Issue] = []
    conveyor_path = run_dir / "conveyor.json"
    if not conveyor_path.exists():
        return out

    try:
        data = json.loads(conveyor_path.read_text())
    except Exception:
        return out

    if data.get("shipped"):
        return out  # no issues — the conveyor delivered

    blocked_at = data.get("final_gate") or "?"
    attempts = data.get("attempts", 0)
    last_feedback = (data.get("last_gate_feedback") or "").strip()

    headline = _gate_headline(blocked_at, last_feedback)
    out.append(Issue(
        severity="error",
        tag=f"blocked at {blocked_at}",
        message=f"After {attempts} attempt(s): {headline}",
    ))
    return out


def _gate_headline(gate: str, feedback: str) -> str:
    """Render one human sentence describing why a gate blocked.

    Reads the first informative line of the gate's feedback and condenses it.
    """
    if not feedback:
        return f"{gate} gate failed (no feedback recorded)"

    short = {
        "code-arrived": "The model emitted zero Java files in its last attempt.",
        "compile": "The emitted Java did not compile — see conveyor.json for the javac errors.",
        "drift": "The emitted Java violated architectural rules (hex purity, OTel, abend semantics).",
        "run": "The emitted Java compiled but failed to run against the fixture.",
        "oracle-diff": "The emitted Java ran but its stdout did not match the curated expected-output.",
    }.get(gate, f"The {gate} gate failed.")

    # Try to pull a one-liner from the feedback (first non-empty line after the GATE header).
    for line in feedback.splitlines():
        line = line.strip()
        if not line or line.startswith("GATE"):
            continue
        if line.startswith("```"):
            continue
        return f"{short} ({line[:140]})"
    return short


def _read_conveyor_state(run_dir: Path) -> dict | None:
    """Read conveyor.json if present. None signals a legacy/incomplete run."""
    p = run_dir / "conveyor.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _overall_status(is_live: bool, phases: list[Phase], issues: list[Issue],
                    conveyor: dict | None) -> str:
    """Map run state to one of: running | shipped | blocked | legacy | smoke.

    - `running`  : a live in-flight run
    - `shipped`  : conveyor.json says shipped=true
    - `blocked`  : conveyor.json says shipped=false (or any unrecoverable issue)
    - `legacy`   : a real run from before the conveyor existed — no conveyor.json
    - `smoke`    : an F3-only smoke build
    """
    if is_live:
        return "running"
    if conveyor is not None:
        return "shipped" if conveyor.get("shipped") else "blocked"
    # No conveyor — distinguish smoke (F3 only) from legacy real runs.
    has_f3_only = any(p.id == "F3" and p.status == "done" for p in phases)
    has_more_than_f3 = any(p.id != "F3" and p.status == "done" for p in phases)
    if has_f3_only and not has_more_than_f3:
        return "smoke"
    return "legacy"


def _summary_line(phases: list[Phase], issues: list[Issue], overall: str,
                  conveyor: dict | None) -> str:
    """One human sentence describing the run's state. No internal jargon."""
    if overall == "shipped":
        attempts = (conveyor or {}).get("attempts", 1)
        plural = "" if attempts == 1 else "s"
        return f"Shipped on attempt {attempts}{('' if attempts == 1 else '')}: code compiles, follows the architecture, runs against the fixture, and matches the expected output." if attempts == 1 else \
               f"Shipped after {attempts} attempt{plural}: code compiles, follows the architecture, runs against the fixture, and matches the expected output."

    if overall == "running":
        running = next((p for p in phases if p.status == "running"), None)
        last_done = max((p.mtime for p in phases if p.status == "done" and p.mtime), default=None)
        running_label = running.label if running else "in flight"
        if last_done is not None:
            quiet = time.time() - last_done
            if quiet > 60:
                quiet_str = f"{int(quiet // 60)}m" if quiet >= 60 else f"{int(quiet)}s"
                return f"Working on {running_label} (no progress in {quiet_str})."
        return f"Working on {running_label}."

    if overall == "blocked":
        headline = next((i for i in issues if i.severity == "error"), None)
        return headline.message if headline else "Blocked."

    if overall == "smoke":
        return "Smoke build — only the context pack was generated, no Codex run."

    if overall == "legacy":
        return "Older run, before the conveyor belt existed — no conveyor record kept."

    return ""


# ---- ETA --------------------------------------------------------------------

def _build_history(runs: list[Run]) -> dict[str, dict]:
    """For each slice, collect total elapsed of recent completed real runs."""
    by_slice: dict[str, list[float]] = {}
    for r in runs:
        if r.kind != "real" or r.is_live or not r.slice or r.elapsed_seconds <= 0:
            continue
        # Only count runs that got through validation OR through F5 (some break before).
        any_done = any(p.status == "done" for p in r.phases)
        if not any_done:
            continue
        by_slice.setdefault(r.slice, []).append(r.elapsed_seconds)
    return {
        s: {
            "n": len(v),
            "median_seconds": statistics.median(v) if v else None,
            "mean_seconds": statistics.mean(v) if v else None,
        }
        for s, v in by_slice.items()
    }


def _estimate_remaining(run: Run, history: dict[str, dict]) -> float | None:
    if not run.slice or run.slice not in history:
        return None
    median = history[run.slice].get("median_seconds")
    if not median:
        return None
    return max(0.0, median - run.elapsed_seconds)
