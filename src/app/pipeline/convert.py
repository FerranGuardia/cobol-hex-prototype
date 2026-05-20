"""F5 — invoke Codex with the converter persona + context pack."""
from __future__ import annotations

import re
from pathlib import Path

from app.core.coordinator import Coordinator
from app.core.schemas import RunConfig

CONVERTER_PROMPT = Path(__file__).resolve().parents[3] / "prompts" / "converter.md"

# Regex that extracts ```java ... ``` fenced blocks tagged with a relative path comment.
JAVA_BLOCK = re.compile(
    r"```java\s+//\s*(?P<path>[^\n]+)\n(?P<body>.*?)```",
    re.DOTALL,
)


def run(cfg: RunConfig, run_id: str, source_file: Path, *, force: bool = False) -> Path:
    """Call Codex with the converter persona + the run's context pack.

    Returns the output directory containing generated .java files.
    """
    coord = Coordinator(cfg)
    context_pack_path = cfg.artifacts_dir / run_id / "context_pack.md"
    if not context_pack_path.exists():
        raise FileNotFoundError(
            f"context_pack.md missing; run `app context-pack --file {source_file}` first"
        )

    prompt = CONVERTER_PROMPT.read_text()
    context = context_pack_path.read_text()

    result = coord.call_codex(prompt=prompt, context=context, force=force)

    out_dir = cfg.artifacts_dir / run_id / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Persist raw response for inspection.
    (cfg.artifacts_dir / run_id / "codex_response.json").write_text(
        __import__("json").dumps(result, indent=2, default=str)
    )

    # Prefer the final-message file (cleaner than stdout which has tool-call traces).
    response_text = str(result.get("final_message") or result.get("stdout") or "")
    # Try to extract structured Java files. If none, dump as raw_output.txt for inspection.
    matches = list(JAVA_BLOCK.finditer(response_text))
    if matches:
        for m in matches:
            rel = m.group("path").strip()
            body = m.group("body")
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
    else:
        (out_dir / "raw_output.txt").write_text(response_text)

    return out_dir
