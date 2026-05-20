"""F3 — build a deterministic markdown context pack for one COBOL program.

No embeddings, no RAG. Every byte is reproducible from the inputs.
Mirrors newABINA's `context_pack.md` discipline.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.schemas import RunConfig

# How much of each ancillary file we inline. Tuning constants; honest defaults.
MAX_README_LINES = 200
MAX_JCL_LINES = 100
MAX_DDL_LINES = 100
MAX_DCL_LINES = 100


def _extract_copy_targets(cobol: str) -> list[str]:
    """Find `COPY <NAME>` statements; return the copybook names."""
    pattern = re.compile(r"^\s*COPY\s+([A-Z0-9_-]+)\s*\.", re.IGNORECASE | re.MULTILINE)
    return sorted(set(m.group(1) for m in pattern.finditer(cobol)))


def _extract_exec_sql_blocks(cobol: str) -> list[str]:
    """Find every EXEC SQL ... END-EXEC block."""
    pattern = re.compile(r"EXEC\s+SQL\b(.*?)END-EXEC", re.IGNORECASE | re.DOTALL)
    return [m.group(0).strip() for m in pattern.finditer(cobol)]


def _read_truncated(path: Path, max_lines: int) -> str:
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        kept = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines elided) ..."]
    else:
        kept = lines
    return "\n".join(kept)


def _find_sibling_dir(start: Path, name: str) -> Path | None:
    """Walk up looking for a sibling directory named `name`."""
    cur = start.parent
    for _ in range(6):
        candidate = cur.parent / name
        if candidate.is_dir():
            return candidate
        cur = cur.parent
    return None


def build(cfg: RunConfig, run_id: str, source_file: Path) -> Path:
    """Produce `artifacts/<run_id>/context_pack.md`."""
    cobol = source_file.read_text(errors="replace")
    copy_targets = _extract_copy_targets(cobol)
    exec_sql_blocks = _extract_exec_sql_blocks(cobol)

    # Locate sibling dirs for DDL / DCL / JCL / README.
    sub_app_root = source_file.parent.parent  # cbl/.. -> sub-app root
    readme = sub_app_root / "README.md"
    ddl_dir = sub_app_root / "ddl"
    dcl_dir = sub_app_root / "dcl"
    jcl_dir = sub_app_root / "jcl"
    cpy_dir = sub_app_root / "cpy"

    sections: list[str] = []
    sections.append(f"# Context Pack — {source_file.name}\n")
    sections.append(f"- **Run ID:** `{run_id}`\n")
    sections.append(f"- **Source:** `{source_file.relative_to(cfg.corpus_root)}`\n")
    sections.append(f"- **Lines:** {cobol.count(chr(10)) + 1}\n")
    sections.append(f"- **COPY targets:** {', '.join(copy_targets) or '(none)'}\n")
    sections.append(f"- **EXEC SQL blocks:** {len(exec_sql_blocks)}\n")
    sections.append("\n---\n")

    if readme.exists():
        sections.append("## Sub-application README (excerpt)\n")
        sections.append("```markdown\n")
        sections.append(_read_truncated(readme, MAX_README_LINES))
        sections.append("\n```\n\n---\n")

    sections.append("## COBOL source\n```cobol\n")
    sections.append(cobol)
    sections.append("\n```\n\n---\n")

    # Copybooks referenced.
    if cpy_dir.exists() and copy_targets:
        sections.append("## Referenced copybooks\n")
        for name in copy_targets:
            for candidate in cpy_dir.glob(f"{name}.*"):
                sections.append(f"### `{candidate.name}`\n```cobol\n")
                sections.append(_read_truncated(candidate, 300))
                sections.append("\n```\n\n")
        sections.append("---\n")

    # DCL host variable declarations.
    if dcl_dir.exists():
        sections.append("## DB2 host variable declarations (DCL)\n")
        for f in sorted(dcl_dir.iterdir()):
            sections.append(f"### `{f.name}`\n```cobol\n")
            sections.append(_read_truncated(f, MAX_DCL_LINES))
            sections.append("\n```\n\n")
        sections.append("---\n")

    # DDL — table schemas.
    if ddl_dir.exists():
        sections.append("## DB2 table DDL\n")
        for f in sorted(ddl_dir.iterdir()):
            sections.append(f"### `{f.name}`\n```sql\n")
            sections.append(_read_truncated(f, MAX_DDL_LINES))
            sections.append("\n```\n\n")
        sections.append("---\n")

    # JCL — the batch workflow.
    if jcl_dir.exists():
        sections.append("## JCL (batch workflow)\n")
        for f in sorted(jcl_dir.iterdir()):
            sections.append(f"### `{f.name}`\n```jcl\n")
            sections.append(_read_truncated(f, MAX_JCL_LINES))
            sections.append("\n```\n\n")
        sections.append("---\n")

    sections.append("## Embedded EXEC SQL blocks (extracted)\n")
    if exec_sql_blocks:
        for i, block in enumerate(exec_sql_blocks, 1):
            sections.append(f"### Block #{i}\n```sql\n{block}\n```\n\n")
    else:
        sections.append("_(none found)_\n")

    out = cfg.artifacts_dir / run_id / "context_pack.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(sections))
    return out
