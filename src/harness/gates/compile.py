"""Gate 2 — javac compiles the emitted Java tree.

Compilation is the strongest deterministic signal that the persona produced
something the JVM accepts. If it doesn't compile, downstream gates are
moot. On failure, the gate feeds the javac diagnostics back to the persona
verbatim — file path, line, column, error string. The persona then knows
exactly what to fix.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from harness.build.deps import classpath, ensure
from harness.gates.result import GateResult


def check(java_root: Path, *, vendor_dir: Path, classes_out: Path) -> GateResult:
    start = time.time()

    # Make sure the minimal JAR set is on disk.
    try:
        ensure(vendor_dir)
    except Exception as exc:
        return GateResult(
            name="compile",
            ok=False,
            feedback=(
                "GATE 2 (compile) FAILED: harness could not fetch the dependency JARs "
                "needed to compile. This is a harness issue, not a persona issue. "
                f"Error: {exc!r}"
            ),
            elapsed_seconds=time.time() - start,
        )

    sources = sorted(str(p) for p in java_root.rglob("*.java"))
    if not sources:
        # Should have been caught by gate 1, but guard anyway.
        return GateResult(
            name="compile",
            ok=False,
            feedback="GATE 2 (compile) skipped — no .java sources to compile.",
            elapsed_seconds=time.time() - start,
        )

    classes_out.mkdir(parents=True, exist_ok=True)
    cp = classpath(vendor_dir)

    cmd = ["javac", "-d", str(classes_out), "-cp", cp, "-Xlint:none"] + sources
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False,
        )
    except subprocess.TimeoutExpired:
        return GateResult(
            name="compile",
            ok=False,
            feedback="GATE 2 (compile) timed out (>120s). Reduce file count or fix infinite recursion in static initializers.",
            elapsed_seconds=time.time() - start,
        )
    except FileNotFoundError:
        return GateResult(
            name="compile",
            ok=False,
            feedback="GATE 2 (compile) FAILED: `javac` not on PATH. Harness setup issue.",
            elapsed_seconds=time.time() - start,
        )

    if proc.returncode == 0:
        # Count .class files for visibility.
        class_count = sum(1 for _ in classes_out.rglob("*.class"))
        return GateResult(
            name="compile",
            ok=True,
            feedback="",
            detail={"class_files": class_count, "sources": len(sources)},
            elapsed_seconds=time.time() - start,
        )

    # Failure path: feed the diagnostics back to the persona.
    errors = (proc.stderr or proc.stdout or "").strip()
    return GateResult(
        name="compile",
        ok=False,
        feedback=(
            "GATE 2 (compile) FAILED. javac produced these diagnostics — fix every one of "
            "them in the Java you emit next. Do not change architectural shape unless the "
            "error specifically requires it; usually the fix is a missing import, a typo, "
            "a wrong method signature, or a missing override.\n\n"
            "```\n"
            f"{errors}\n"
            "```"
        ),
        detail={
            "returncode": proc.returncode,
            "sources": len(sources),
            "stderr_excerpt": errors[:4000],
        },
        elapsed_seconds=time.time() - start,
    )
