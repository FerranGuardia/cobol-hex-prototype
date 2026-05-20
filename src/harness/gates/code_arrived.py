"""Gate 1 — Code arrived.

The cheapest, most load-bearing gate. If the persona didn't write any .java
files, the entire pipeline is broken; everything downstream is moot. We
retry the persona with a blunt prompt addition telling it to emit Java now.
"""
from __future__ import annotations

import time
from pathlib import Path

from harness.gates.result import GateResult


MIN_FILES = 1


def check(java_root: Path, *, slice_name: str) -> GateResult:
    start = time.time()
    if not java_root.exists():
        return GateResult(
            name="code-arrived",
            ok=False,
            feedback=(
                "GATE 1 (code-arrived) FAILED: the persona emitted zero Java files in this run. "
                "The pipeline cannot proceed without code. Emit Java files now, one per file, in "
                "fenced ```java // <relative-path>``` blocks under "
                f"`com/example/cobol/{slice_name.lower()}/`. No JSON, no markdown commentary, no "
                "explanations — only fenced Java blocks. This is your only deliverable."
            ),
            elapsed_seconds=time.time() - start,
        )

    java_files = list(java_root.rglob("*.java"))
    n = len(java_files)
    if n < MIN_FILES:
        return GateResult(
            name="code-arrived",
            ok=False,
            feedback=(
                f"GATE 1 (code-arrived) FAILED: only {n} Java file(s) emitted; the pipeline "
                "needs at least one Java file under the slice's package. Re-emit the full hex "
                "architecture: domain/model/, domain/port/, application/usecase/, adapter/in/batch/, "
                "adapter/out/<system>/, infra/observability/. Emit each as a fenced "
                "```java // <relative-path>``` block."
            ),
            detail={"files_found": n, "paths": [str(p.relative_to(java_root)) for p in java_files]},
            elapsed_seconds=time.time() - start,
        )

    return GateResult(
        name="code-arrived",
        ok=True,
        feedback="",
        detail={
            "files_found": n,
            "paths": sorted(str(p.relative_to(java_root)) for p in java_files),
        },
        elapsed_seconds=time.time() - start,
    )
