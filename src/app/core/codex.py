"""Thin wrapper around the Codex CLI subprocess.

Tested against `codex-cli 0.131.0-alpha.9` (the binary that ships inside Codex.app).
Flag reference: `codex exec --help`. Notes:

- We use `-s read-only` so Codex can read source files but never write — our pipeline
  controls all writes. The model output ends up in the `--output-last-message` file.
- `--ephemeral` + `--ignore-user-config` + `--ignore-rules` make runs independent of
  the user's `~/.codex/` setup (reproducibility across machines).
- No native `--seed` or `--temperature` flags exist. We control determinism via
  prompt+context hashing in `core/determinism.py` and a `-c temperature=0` config
  override (passed as TOML to the model provider).
- The desktop-app-bundled binary lives at
  `/Applications/Codex.app/Contents/Resources/codex` on macOS. Set `CODEX_BIN` to
  the absolute path if `codex` is not on `PATH`.
"""
from __future__ import annotations

import subprocess
import tempfile
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
        """Invoke `codex exec` non-interactively.

        Returns a dict with `stdout`, `stderr`, `rc`, and `final_message` keys.
        `final_message` is the model's final response, written by Codex to a temp file
        via `--output-last-message`. It is what downstream parsing should consume; the
        stdout stream also contains tool-call traces and progress events.
        """
        with tempfile.NamedTemporaryFile(
            "r+", suffix=".txt", delete=False, encoding="utf-8"
        ) as out_file:
            out_path = Path(out_file.name)

        argv: list[str] = [
            self.codex_bin,
            "exec",
            "-s", "read-only",
            "-c", f"temperature={self.temperature}",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "-o", str(out_path),
        ]
        # Only pin a model if one was explicitly set; otherwise let Codex use the
        # account-appropriate default (e.g., gpt-5.5 on a ChatGPT subscription).
        if self.model and self.model.lower() not in {"", "default", "auto"}:
            argv.extend(["-m", self.model])
        if self.workdir:
            argv.extend(["-C", str(self.workdir)])

        try:
            result = subprocess.run(
                argv,
                input=self.prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            final_msg = out_path.read_text() if out_path.exists() else ""
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "rc": result.returncode,
                "final_message": final_msg,
                "argv": " ".join(argv),
            }
        except FileNotFoundError as e:
            return {
                "stdout": "",
                "stderr": f"codex CLI not found at {self.codex_bin!r}: {e}",
                "rc": 127,
                "final_message": "",
                "argv": " ".join(argv),
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"timeout after {self.timeout_seconds}s",
                "rc": 124,
                "final_message": "",
                "argv": " ".join(argv),
            }
        finally:
            try:
                out_path.unlink()
            except OSError:
                pass
