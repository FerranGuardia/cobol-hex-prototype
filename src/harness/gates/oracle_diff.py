"""Gate 5 — Diff captured stdout against the curated expected-output.txt.

This is the load-bearing T2-EQUIVALENCE gate: the program runs against the
fixture, produces stdout, and that stdout must match the human-curated
expected-output.txt byte-for-byte (modulo trailing whitespace tolerance).

When the diff fails, the unified diff is fed back to the persona — they
see exactly which line they got wrong. No "the test is unhappy" handwave;
the persona sees the diff just like a human reviewer would.
"""
from __future__ import annotations

import difflib
import time
from pathlib import Path

from harness.gates.result import GateResult


MAX_DIFF_LINES_IN_FEEDBACK = 120


def check(stdout: str, *, expected_path: Path, slice_name: str) -> GateResult:
    start = time.time()

    if not expected_path.exists():
        return GateResult(
            name="oracle-diff",
            ok=False,
            feedback=(
                f"GATE 5 (oracle-diff) cannot run — expected-output file not found at "
                f"{expected_path}. Curate `golden-outputs/{slice_name}.expected-output.txt` "
                "first (this is harness setup, not persona work)."
            ),
            elapsed_seconds=time.time() - start,
        )

    expected = expected_path.read_text(errors="replace")
    actual = stdout

    # Tolerance: normalize trailing whitespace per line + final-newline.
    exp_lines = [L.rstrip() for L in expected.splitlines()]
    act_lines = [L.rstrip() for L in actual.splitlines()]

    if exp_lines == act_lines:
        return GateResult(
            name="oracle-diff",
            ok=True,
            feedback="",
            detail={
                "expected_lines": len(exp_lines),
                "actual_lines": len(act_lines),
                "matched": True,
            },
            elapsed_seconds=time.time() - start,
        )

    diff = list(difflib.unified_diff(
        exp_lines, act_lines,
        fromfile=str(expected_path.name),
        tofile="actual_stdout.txt",
        lineterm="",
    ))
    truncated = diff[:MAX_DIFF_LINES_IN_FEEDBACK]
    elided = max(0, len(diff) - MAX_DIFF_LINES_IN_FEEDBACK)

    feedback_lines = [
        "GATE 5 (oracle-diff) FAILED. Your program runs but its stdout does not match "
        f"the curated expected-output for `{slice_name}`. The unified diff below shows "
        "the differences (`-` is expected, `+` is what you produced):",
        "",
        "```diff",
        *truncated,
        "```",
    ]
    if elided:
        feedback_lines.append(f"... ({elided} more diff lines elided) ...")
    feedback_lines.append("")
    feedback_lines.append(
        "Fix the emission so stdout matches expected byte-for-byte. Likely sources: "
        "wrong record-format parsing (read fixed-width bytes, not lines), wrong charset "
        "(EBCDIC cp037 vs ASCII), wrong DISPLAY ordering, duplicated lines in error "
        "paths, missing start/end banner. The Iria runtime contract in the Context Pack "
        "tells you the displayContract.startLine/endLine/perRecord/ioErrorLines verbatim."
    )

    return GateResult(
        name="oracle-diff",
        ok=False,
        feedback="\n".join(feedback_lines),
        detail={
            "expected_lines": len(exp_lines),
            "actual_lines": len(act_lines),
            "diff_lines": len(diff),
            "diff_truncated": "\n".join(truncated),
        },
        elapsed_seconds=time.time() - start,
    )
