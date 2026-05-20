"""F6 — apply the four acceptance tiers to a run's output.

This is intentionally lean for the first iteration. Each tier check is replaceable.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from app.core.schemas import RunConfig, TierResult, ValidationReport


def _t1_check(output_dir: Path) -> TierResult:
    """Hard invariants. Cheap regex/AST checks; no JVM required at this stage."""
    tags: list[str] = []
    details: dict = {}

    java_files = sorted(output_dir.rglob("*.java"))
    details["java_files"] = len(java_files)

    if not java_files:
        return TierResult(status="fail", failure_tags=["T1-NO-OUTPUT"], details=details)

    text_all = "\n".join(p.read_text() for p in java_files)

    # Hex shape (cheap): every file path should match a permitted layer
    permitted = re.compile(r"/(domain|application|adapter|infra)/")
    bad_paths = [str(p) for p in java_files if not permitted.search(str(p))]
    if bad_paths:
        tags.append("T1-HEX-VIOLATION")
        details["unparented_files"] = bad_paths[:5]

    # No COBOL-style identifiers leaking
    if re.search(r"\b[A-Z][A-Z0-9_-]+\s*-[A-Z]", text_all):
        # very loose; legitimate hits possible. Mark only if frequent.
        details["cobol_id_hits"] = len(re.findall(r"\b[A-Z][A-Z0-9_-]+\s*-[A-Z]", text_all))
        if details["cobol_id_hits"] > 5:
            tags.append("T1-COBOL-IDIOM-LEAK")

    # Stub return statements
    if re.search(r"throw\s+new\s+UnsupportedOperationException", text_all):
        tags.append("T1-COBOL-IDIOM-LEAK")  # use STUB tag once added; reusing for now

    # Provenance header presence
    if not all(p.read_text().startswith("/*") and "Generated from:" in p.read_text()[:500]
               for p in java_files):
        tags.append("T1-NO-PROVENANCE")

    # Compile check (optional — only if mvn is on path AND a pom exists)
    if (output_dir / "pom.xml").exists() and shutil.which("mvn"):
        rc = subprocess.run(
            ["mvn", "-q", "-DskipTests", "compile"],
            cwd=output_dir, capture_output=True, text=True, check=False,
        ).returncode
        if rc != 0:
            tags.append("T1-COMPILE-ERROR")

    status = "pass" if not tags else "fail"
    return TierResult(status=status, failure_tags=tags, details=details)


def _t2_check(golden_master_path: Path, output_dir: Path) -> TierResult:
    """Semantic equivalence. Without a runtime we can only do static cross-reference."""
    if not golden_master_path.exists():
        return TierResult(status="skip", details={"reason": "no golden master"})

    gm = json.loads(golden_master_path.read_text())
    assertions = gm.get("assertions", [])
    if not assertions:
        return TierResult(status="skip", details={"reason": "empty golden master"})

    text_all = "\n".join(p.read_text() for p in sorted(output_dir.rglob("*.java")))

    # Naive: count how many DDL table names mentioned in golden master appear in output.
    matched = 0
    for a in assertions:
        exp = a.get("expected_output") or {}
        if isinstance(exp, dict):
            table = exp.get("table")
            if table and (table.split(".")[-1] in text_all):
                matched += 1
                continue
        # Otherwise check feature description tokens.
        desc = a.get("description", "")
        tokens = [t for t in re.findall(r"[A-Za-z]{4,}", desc.lower()) if t not in {"the", "with"}]
        if tokens and sum(1 for t in tokens if t in text_all.lower()) / len(tokens) > 0.5:
            matched += 1

    score = matched / len(assertions)
    status = "pass" if score >= 0.95 else "fail"
    tags = [] if status == "pass" else ["T2-PARTIAL-COVERAGE"]
    return TierResult(status=status, score=score, failure_tags=tags,
                      details={"matched": matched, "total": len(assertions)})


def _t3_check(output_dir: Path) -> TierResult:
    """Determinism (drift). Real check is run separately via `app drift`."""
    return TierResult(status="skip", details={"reason": "use `app drift` for T3"})


def _t4_check(run_dir: Path) -> TierResult:
    """Economics. Reads codex_response.json if present."""
    resp_path = run_dir / "codex_response.json"
    if not resp_path.exists():
        return TierResult(status="skip", details={"reason": "no codex response recorded"})
    return TierResult(status="pass", details={"note": "real metrics added once codex CLI provides them"})


def run(cfg: RunConfig, run_id: str, source_file: Path | None = None) -> ValidationReport:
    run_dir = cfg.artifacts_dir / run_id
    out_dir = run_dir / "output"
    gm_path = run_dir / "golden_master.json"

    # If caller didn't provide source_file, try to recover it from the golden master.
    if source_file is None and gm_path.exists():
        try:
            gm = json.loads(gm_path.read_text())
            sf = gm.get("source_file")
            source_file = Path(sf) if sf else Path("(unknown)")
        except (json.JSONDecodeError, OSError):
            source_file = Path("(unknown)")
    elif source_file is None:
        source_file = Path("(unknown)")

    t1 = _t1_check(out_dir)
    t2 = _t2_check(gm_path, out_dir)
    t3 = _t3_check(out_dir)
    t4 = _t4_check(run_dir)
    overall = "pass" if t1.status == "pass" and t2.status in {"pass", "skip"} else "fail"

    report = ValidationReport(
        run_id=run_id,
        source_file=source_file,
        t1=t1, t2=t2, t3=t3, t4=t4,
        overall=overall,
    )
    (run_dir / "validation.json").write_text(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
    return report
