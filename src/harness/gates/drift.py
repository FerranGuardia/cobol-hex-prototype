"""Gate 3 — hex / OTel / abend drift checks.

Wraps the existing `harness/checks/drift_checks.py` in the gate interface.
On failure, every finding's tag + message + path is fed back to the
persona so it knows exactly which rule it violated where.
"""
from __future__ import annotations

import time
from pathlib import Path

from harness.checks.drift_checks import run_all as run_drift_all
from harness.extract.cobol_facts import extract as extract_cobol_facts
from harness.gates.result import GateResult


def check(java_root: Path, *, cobol_source: Path) -> GateResult:
    start = time.time()

    facts = extract_cobol_facts(cobol_source)
    report = run_drift_all(facts, java_root)

    if report.ok:
        return GateResult(
            name="drift",
            ok=True,
            feedback="",
            detail={"checks_run": len(report.findings) + 1, "findings": 0},
            elapsed_seconds=time.time() - start,
        )

    # Feed structured findings back to the persona.
    fails = [f for f in report.findings if f.severity == "fail"]
    warns = [f for f in report.findings if f.severity == "warn"]

    lines: list[str] = ["GATE 3 (drift) FAILED. Fix each violation below in your next emission:"]
    for f in fails:
        lines.append(f"- `{f.code}` at `{f.java_file}` (cobol: {f.cobol_anchor}): {f.message}")
    if warns:
        lines.append("\nWarnings (non-blocking, but should still be fixed):")
        for f in warns:
            lines.append(f"- `{f.code}` at `{f.java_file}` (cobol: {f.cobol_anchor}): {f.message}")
    lines.append("")
    lines.append(
        "Remember: when the Context Pack includes an Iria runtime contract, take "
        "file organization, record format, encoding, abend semantics, and field "
        "layout verbatim from it — that contract is verified by a real COBOL runtime."
    )

    return GateResult(
        name="drift",
        ok=False,
        feedback="\n".join(lines),
        detail={
            "fails": len(fails),
            "warns": len(warns),
            "report": report.to_dict(),
        },
        elapsed_seconds=time.time() - start,
    )
