"""Deterministic harness gates — the conveyor belt the persona must pass.

Each gate is a pure function: (artifacts) -> GateResult(ok, feedback).
On failure, `feedback` becomes the retry text appended to the next persona
call. The persona keeps going until every gate passes or hard-fail at N
retries. No LLM-judging-LLM. No silent passes. The pipeline either ships a
validated deliverable or surfaces exactly which gate blocked.

Order, matching SPEC.md:
  1. code_arrived  — at least one .java file emitted
  2. compile       — javac the tree
  3. drift         — hex / OTel / abend rules
  4. run_program   — execute main against the fixture
  5. oracle_diff   — diff stdout vs expected-output.txt

This module exports the dataclass + each gate function. The retry orchestrator
in pipeline/convert.py composes them.
"""
from __future__ import annotations

from harness.gates.result import GateResult
from harness.gates.code_arrived import check as gate_code_arrived
from harness.gates.compile import check as gate_compile
from harness.gates.drift import check as gate_drift
from harness.gates.run_program import check as gate_run
from harness.gates.oracle_diff import check as gate_oracle_diff

__all__ = [
    "GateResult",
    "gate_code_arrived",
    "gate_compile",
    "gate_drift",
    "gate_run",
    "gate_oracle_diff",
]
