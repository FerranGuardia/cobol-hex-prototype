"""Gate 4 — Run the program against the fixture.

Finds the main class by scanning the compiled .class tree (or sources)
for `public static void main(String[] args)`, then invokes
`java -cp <vendor>:<classes> <fqcn>` with the fixture path supplied as
both env var (`CARDFILE`) and CLI arg (so the persona can pick either
convention). Captures stdout and returns it via detail so the next gate
can diff it.

A non-zero exit code is treated as a hard fail; the persona must produce a
program that exits 0 on the canonical fixture. The captured stderr is
fed back so JVM exceptions / NPEs / class-not-found are visible in the
retry prompt.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from harness.build.deps import classpath
from harness.gates.result import GateResult


_MAIN_RE = re.compile(
    r"public\s+static\s+(?:final\s+)?void\s+main\s*\(\s*String\s*(?:\[\]|\.\.\.)\s*\w+\s*\)"
)
_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_PUBLIC_CLASS_RE = re.compile(r"public\s+(?:final\s+)?class\s+(\w+)")


def check(
    java_root: Path,
    *,
    classes_out: Path,
    vendor_dir: Path,
    fixture_path: Path,
    slice_name: str,
    timeout_seconds: int = 30,
) -> GateResult:
    start = time.time()

    main_fqcn = _find_main_class(java_root)
    if main_fqcn is None:
        return GateResult(
            name="run",
            ok=False,
            feedback=(
                "GATE 4 (run) FAILED: no class with `public static void main(String[] args)` "
                f"found in the emitted tree. The persona must produce a driver in "
                f"`adapter/in/batch/Cbact{slice_name[4:].lower() if slice_name.startswith('CBACT') else slice_name.lower()}BatchRunner.java` "
                "(or equivalent) with a main method that reads the fixture from CARDFILE env var "
                "or args[0], wires the use case, and invokes it. Add the main method now."
            ),
            elapsed_seconds=time.time() - start,
        )

    if not fixture_path.exists():
        return GateResult(
            name="run",
            ok=False,
            feedback=(
                f"GATE 4 (run) cannot run — fixture file not found at {fixture_path}. "
                "This is a harness configuration issue, not a persona issue."
            ),
            elapsed_seconds=time.time() - start,
        )

    cp = classpath(vendor_dir, extra=[classes_out])
    env = {**os.environ, "CARDFILE": str(fixture_path)}
    cmd = ["java", "-cp", cp, main_fqcn, str(fixture_path)]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout_seconds, check=False, env=env,
        )
    except subprocess.TimeoutExpired:
        return GateResult(
            name="run",
            ok=False,
            feedback=(
                f"GATE 4 (run) timed out after {timeout_seconds}s. The program is likely "
                "stuck in an infinite loop or waiting for input. Make sure the main loop "
                "terminates when the fixture is exhausted (FILE STATUS = '10')."
            ),
            elapsed_seconds=time.time() - start,
        )
    except FileNotFoundError:
        return GateResult(
            name="run",
            ok=False,
            feedback="GATE 4 (run) FAILED: `java` not on PATH. Harness setup issue.",
            elapsed_seconds=time.time() - start,
        )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode != 0:
        return GateResult(
            name="run",
            ok=False,
            feedback=(
                f"GATE 4 (run) FAILED with exit code {proc.returncode} running `java {main_fqcn}`. "
                "JVM stderr below — fix the runtime error in your next emission. "
                "Common causes: NullPointerException in a constructor, ClassNotFoundException "
                "for a missing class, NumberFormatException parsing fixed-width numeric fields "
                "with EBCDIC padding, ArrayIndexOutOfBoundsException on a short record.\n\n"
                "```\n"
                f"{stderr[:3000]}\n"
                "```"
            ),
            detail={
                "main_class": main_fqcn,
                "returncode": proc.returncode,
                "stdout_bytes": len(stdout),
                "stderr_excerpt": stderr[:4000],
                "stdout_excerpt": stdout[:2000],
            },
            elapsed_seconds=time.time() - start,
        )

    return GateResult(
        name="run",
        ok=True,
        feedback="",
        detail={
            "main_class": main_fqcn,
            "returncode": 0,
            "stdout": stdout,           # full stdout for next gate
            "stdout_bytes": len(stdout),
            "stderr_excerpt": stderr[:1000],
        },
        elapsed_seconds=time.time() - start,
    )


def _find_main_class(java_root: Path) -> str | None:
    """Scan .java sources for the first `public static void main` definition.

    We scan sources rather than .class files because (a) we already have them and
    (b) javap is more friction than it's worth.
    """
    for path in sorted(java_root.rglob("*.java")):
        text = path.read_text(errors="replace")
        if not _MAIN_RE.search(text):
            continue
        pkg_match = _PACKAGE_RE.search(text)
        cls_match = _PUBLIC_CLASS_RE.search(text)
        if not cls_match:
            continue
        pkg = pkg_match.group(1) if pkg_match else ""
        cls = cls_match.group(1)
        return f"{pkg}.{cls}" if pkg else cls
    return None
