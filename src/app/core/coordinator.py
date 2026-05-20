"""Orchestrates phases. Owns cache + drift + run IDs.

Thin by design — most logic lives in `app.pipeline.*`. The coordinator's job is to
make every phase reproducible: same input ⇒ same output, or honest drift report.
"""
from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime
from pathlib import Path

from app.core.codex import CodexCall
from app.core.determinism import CacheStore, cache_key, diff_ast_java, diff_byte
from app.core.schemas import RunConfig


class Coordinator:
    def __init__(self, cfg: RunConfig) -> None:
        self.cfg = cfg
        self.cache = CacheStore(cfg.cache_dir)
        self.cfg.artifacts_dir.mkdir(parents=True, exist_ok=True)

    # ----- run ids ----------------------------------------------------------

    def new_run_id(self, source_file: Path) -> str:
        """Stable-ish run id: timestamp + 8 chars of input-content hash."""
        h = hashlib.sha256(source_file.read_bytes()).hexdigest()[:8]
        return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{h}"

    def artifact_path(self, run_id: str, *parts: str) -> Path:
        path = self.cfg.artifacts_dir / run_id
        for p in parts:
            path = path / p
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def git_sha(self) -> str | None:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, check=False, timeout=5,
            )
            return r.stdout.strip() or None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    # ----- llm call with cache ---------------------------------------------

    def call_codex(self, *, prompt: str, context: str, force: bool = False) -> dict:
        """Cache-aware Codex call. Returns the cached result if available."""
        key = cache_key(
            prompt=prompt, context=context,
            model=self.cfg.model, seed=self.cfg.seed,
        )
        full_prompt = f"{prompt}\n\n---CONTEXT---\n{context}"

        def runner() -> dict:
            return CodexCall(
                prompt=full_prompt,
                model=self.cfg.model,
                seed=self.cfg.seed,
                temperature=self.cfg.temperature,
                timeout_seconds=self.cfg.timeout_seconds,
                codex_bin=self.cfg.codex_bin,
            ).run() | {"cache_key": key}

        return self.cache.run_or_load(key, runner, force=force)

    # ----- drift (T3) -------------------------------------------------------

    def drift(self, source_file: Path, *, runs: int = 3) -> dict:
        """Run the convert phase `runs` times, report divergence.

        Note: uses the cache only on the first run; subsequent runs use --force to
        actually exercise the LLM and observe noise.
        """
        from app.pipeline import convert  # local import to avoid cycle

        outputs: list[str] = []
        run_ids: list[str] = []
        for i in range(runs):
            rid = self.new_run_id(source_file) + f"-drift{i}"
            convert.run(self.cfg, rid, source_file, force=(i > 0))
            outdir = self.artifact_path(rid, "output")
            joined = self._concat_outputs(outdir)
            outputs.append(joined)
            run_ids.append(rid)

        byte_pairs = sum(1 for i in range(len(outputs)) for j in range(i + 1, len(outputs))
                         if diff_byte(outputs[i], outputs[j]))
        ast_pairs = sum(1 for i in range(len(outputs)) for j in range(i + 1, len(outputs))
                        if diff_ast_java(outputs[i], outputs[j]))
        total_pairs = runs * (runs - 1) // 2

        return {
            "runs": runs,
            "run_ids": run_ids,
            "byte_identical_pairs": byte_pairs,
            "ast_equivalent_pairs": ast_pairs,
            "total_pairs": total_pairs,
            "byte_identical_rate": byte_pairs / total_pairs if total_pairs else 1.0,
            "ast_equivalent_rate": ast_pairs / total_pairs if total_pairs else 1.0,
        }

    @staticmethod
    def _concat_outputs(outdir: Path) -> str:
        if not outdir.exists():
            return ""
        parts: list[str] = []
        for p in sorted(outdir.rglob("*.java")):
            parts.append(f"// FILE: {p.relative_to(outdir)}\n{p.read_text()}")
        return "\n".join(parts)
