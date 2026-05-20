"""GateResult — the canonical shape every gate returns."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GateResult:
    name: str               # e.g. "code-arrived", "compile", "drift", "run", "oracle-diff"
    ok: bool                # pass / fail
    feedback: str           # for retry: the exact prose appended to next persona call
    detail: dict[str, Any] = field(default_factory=dict)  # structured info for UI / forensics
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "feedback": self.feedback,
            "detail": self.detail,
            "elapsed_seconds": self.elapsed_seconds,
        }
