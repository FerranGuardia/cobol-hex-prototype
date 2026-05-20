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

# Phase definitions. Order matters — earlier phases run first.
PHASES = [
    {"id": "F3", "label": "context pack",    "path": "context_pack.md",                                       "kind": "file"},
    {"id": "F4", "label": "golden master",   "path": "golden_master.json",                                    "kind": "file"},
    {"id": "F5a","label": "code-author",     "path": "raw/code-author/response-0.json",                       "kind": "file"},
    {"id": "F5b","label": "test-author",     "path": "raw/test-author/response-0.json",                       "kind": "file"},
    {"id": "F5d","label": "contract-diff",   "path": "contracts/diff.json",                                   "kind": "file"},
    {"id": "F6", "label": "validate",        "path": "validation.json",                                       "kind": "file"},
    {"id": "F6d","label": "drift-check",     "path": "drift.json",                                            "kind": "file"},
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
    recent = [r for r in runs if not r.is_live][:8]
    open_issues = [
        {"run_id": r.run_id, "slice": r.slice, **i.__dict__}
        for r in runs[:6]
        for i in r.issues
    ]

    return {
        "generated_at": time.time(),
        "artifacts_root": str(artifacts_root),
        "live": [r.to_dict() for r in live],
        "recent": [r.to_dict() for r in recent],
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
    overall = _overall_status(is_live, phases, issues)
    summary = _summary_line(phases, issues, overall)

    return Run(
        run_id=run_id, kind=kind, slice=slice_name,
        started_at=started_at, last_mtime=last_mtime, elapsed_seconds=elapsed,
        is_live=is_live, overall_status=overall,
        phases=phases, issues=issues, summary_line=summary,
    )


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
    out: list[Issue] = []
    val_path = run_dir / "validation.json"
    if val_path.exists():
        try:
            data = json.loads(val_path.read_text())
            for tier_key in ("t1", "t2", "t3", "t4"):
                tier = data.get(tier_key) or {}
                tags = tier.get("failure_tags") or []
                for tag in tags:
                    sev = "error" if tier_key in ("t1",) else "warn"
                    msg = _fmt_tier_msg(tier_key, tier, tag)
                    out.append(Issue(severity=sev, tag=tag, message=msg))
        except Exception:
            pass

    drift_path = run_dir / "drift.json"
    if drift_path.exists():
        try:
            data = json.loads(drift_path.read_text())
            for f in data.get("findings", []):
                sev = f.get("severity", "warn")
                tag = f.get("rule") or f.get("tag") or "drift"
                msg = f.get("message") or json.dumps(f)
                out.append(Issue(severity=sev, tag=tag, message=msg))
        except Exception:
            pass

    diff_path = run_dir / "contracts" / "diff.json"
    if diff_path.exists():
        try:
            data = json.loads(diff_path.read_text())
            s = data.get("summary") or {}
            crit = s.get("critical", 0)
            mat = s.get("material", 0)
            if crit:
                out.append(Issue(severity="error", tag="T2-CONTRACT-MISMATCH",
                                 message=f"{crit} critical contract differences between personas"))
            if mat:
                out.append(Issue(severity="warn", tag="T2-CONTRACT-MISMATCH",
                                 message=f"{mat} material contract differences between personas"))
        except Exception:
            pass

    return out


def _fmt_tier_msg(tier_key: str, tier: dict, tag: str) -> str:
    details = tier.get("details") or {}
    if tier_key == "t1" and "java_files" in details:
        return f"{tag} · {details['java_files']} java files emitted"
    if tier_key == "t2" and "matched" in details:
        return f"{tag} · {details.get('matched',0)}/{details.get('total',0)} assertions"
    return tag


def _overall_status(is_live: bool, phases: list[Phase], issues: list[Issue]) -> str:
    if is_live:
        return "running"
    errors = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warn"]
    if errors:
        return "blocked"
    if warns:
        return "issues"
    return "ok"


def _summary_line(phases: list[Phase], issues: list[Issue], overall: str) -> str:
    if overall == "ok":
        return "all phases pass"
    if overall == "running":
        running = next((p for p in phases if p.status == "running"), None)
        # If no new artifact in >60s, the persona is either truly thinking (Codex
        # call subprocess can run 5-10m without disk writes) OR the process died.
        # Surface the elapsed-since-last-write so the user can judge.
        last_done = max((p.mtime for p in phases if p.status == "done" and p.mtime), default=None)
        if last_done is not None:
            quiet = time.time() - last_done
            if quiet > 60:
                quiet_str = f"{int(quiet // 60)}m{int(quiet % 60)}s" if quiet >= 60 else f"{int(quiet)}s"
                return f"running {running.label} · last write {quiet_str} ago" if running else f"in flight · quiet {quiet_str}"
        return f"running {running.label}" if running else "in flight"
    headline = next((i for i in issues if i.severity == "error"),
                    next((i for i in issues if i.severity == "warn"), None))
    return f"{headline.tag}: {headline.message}" if headline else "no detail"


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
