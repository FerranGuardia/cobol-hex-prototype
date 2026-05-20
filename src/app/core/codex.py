"""Thin wrapper around the Codex CLI subprocess."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodexCall:
    """One Codex invocation. Captures inputs and outputs for the cache + drift store."""

    prompt: str
    model: str
    seed: int
    temperature: float
    timeout_seconds: int = 600
    workdir: Path | None = None
    codex_bin: str = "codex"

    def run(self) -> dict[str, str | int]:
        """Invoke Codex CLI non-interactively. Returns dict with stdout/stderr/rc.

        The exact CLI surface is version-dependent. Adjust the argv as needed:
        - Current openai/codex CLI: `codex exec --model <m> --json --cd <dir> <prompt>`
        - On differences, prefer making this function adapt; do not change call sites.
        """
        argv: list[str] = [
            self.codex_bin,
            "exec",
            "--model",
            self.model,
            "--ask-for-approval",
            "never",
            "--full-auto",
        ]
        if self.workdir:
            argv.extend(["--cd", str(self.workdir)])

        try:
            result = subprocess.run(
                argv,
                input=self.prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "rc": result.returncode,
            }
        except FileNotFoundError as e:
            return {
                "stdout": "",
                "stderr": f"codex CLI not found at {self.codex_bin!r}: {e}",
                "rc": 127,
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"timeout after {self.timeout_seconds}s",
                "rc": 124,
            }
