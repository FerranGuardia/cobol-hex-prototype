"""F3 — build a deterministic markdown context pack for one COBOL program.

No embeddings, no RAG. Every byte is reproducible from the inputs.
Mirrors newABINA's `context_pack.md` discipline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.schemas import RunConfig

# How much of each ancillary file we inline. Tuning constants; honest defaults.
MAX_README_LINES = 200
MAX_JCL_LINES = 100
MAX_DDL_LINES = 100
MAX_DCL_LINES = 100

# Which drift modes the iria contract closes by construction when present.
# Wired here so the persona-facing section can name them explicitly — knowing
# WHY a fact is authoritative is what stops the persona from re-deriving it.
IRIA_DRIFT_MODES_CLOSED = [
    ("T2-FILE-ORG-DRIFT", "datasets[*].organization / accessMode / recordFormat / recordLength / recordKey are explicit"),
    ("T2-CHARSET-IMPLICIT", "datasets[*].encoding + ccsid are explicit (EBCDIC cp037 with ASCII fallback path)"),
    ("T2-ABEND-CATCHABLE", "execution.abend.semantics is explicit ('terminal — process exits, never returns')"),
    ("field-layout ambiguity", "datasets[*].fields gives byte offsets + lengths + types directly"),
]


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


def _load_iria_contract(repo_root: Path, program_name: str) -> tuple[Path, dict] | None:
    """Locate and parse `iria/contracts/<PROGRAM>.json` if present.

    Returned dict is the parsed contract; caller renders the persona-facing
    section. Returns None when no contract is committed yet (most slices),
    which keeps the pack honest about whether iria coverage exists.
    """
    path = repo_root / "iria" / "contracts" / f"{program_name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return path, data


def _render_iria_contract(path: Path, data: dict, *, repo_root: Path) -> list[str]:
    """Render the iria contract section: framing + raw JSON + drift-mode map.

    The persona reads this BEFORE the COBOL source, so its first impression
    of the slice is "here are facts that were verified by a real COBOL
    runtime," not "here is ambiguous COBOL text I need to interpret."
    """
    rel = path.relative_to(repo_root)
    runtime = (data.get("execution") or {}).get("iriaRuntime") or {}
    runtime_status = runtime.get("status", "unknown")
    parse_ok = runtime.get("parseOk")
    run_ok = runtime.get("runOk")
    rc_ok = runtime.get("rcOk")
    expected_rc = runtime.get("expectedRc")

    out: list[str] = []
    out.append("## Iria runtime contract (AUTHORITATIVE — DO NOT RE-DERIVE)\n")
    out.append(
        "This contract is upstream input from xavi's `iria-carddemo-lab`. The program "
        f"was executed end-to-end by the Iria COBOL runtime: `status={runtime_status}`, "
        f"`parseOk={parse_ok}`, `runOk={run_ok}`, `rcOk={rc_ok}`, `expectedRc={expected_rc}`. "
        "The dataset bindings, encoding, record layout, and abend semantics below are "
        "VERIFIED FACTS about how this program runs, not interpretations of the COBOL text.\n\n"
    )
    out.append(f"- **Path:** `{rel}`\n")
    out.append("- **Closes by construction (do not also re-check from COBOL text):**\n")
    for tag, why in IRIA_DRIFT_MODES_CLOSED:
        out.append(f"  - `{tag}` — {why}\n")
    out.append(
        "- **Persona obligation:** when this section disagrees with what the COBOL text "
        "*appears* to say (e.g., the SELECT phrasing is ambiguous, the abend service is "
        "spelled non-obviously), THIS contract wins. The COBOL text is the implementation; "
        "this contract is the verified physical reality.\n"
    )
    out.append("- **For test-author specifically:** the `displayContract`, `expectedOutput.asciiOraclePath`, "
               "and `fileStatusCodesBranched` fields are direct fixture-grounded postcondition material — "
               "use them for `@Tag(\"T2-equivalence\")` and `@Tag(\"T2-fixture\")` assertions.\n\n")
    out.append("```json\n")
    out.append(json.dumps(data, indent=2, ensure_ascii=False))
    out.append("\n```\n\n---\n")
    return out


def build(cfg: RunConfig, run_id: str, source_file: Path) -> Path:
    """Produce `artifacts/<run_id>/context_pack.md`."""
    source_file = source_file.resolve()
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

    # Iria contract: authoritative upstream input from xavi's iria-carddemo-lab.
    # When present, the persona doesn't infer file org / encoding / abend / field
    # layout — those facts come from a program that provably executes on the
    # iria COBOL runtime end-to-end (parseOk + runOk + rc=0).
    program_name = source_file.stem.upper()
    repo_root = Path(__file__).resolve().parents[3]
    iria = _load_iria_contract(repo_root, program_name)

    sections: list[str] = []
    sections.append(f"# Context Pack — {source_file.name}\n")
    sections.append(f"- **Run ID:** `{run_id}`\n")
    sections.append(f"- **Source:** `{source_file.relative_to(cfg.corpus_root)}`\n")
    sections.append(f"- **Lines:** {cobol.count(chr(10)) + 1}\n")
    sections.append(f"- **COPY targets:** {', '.join(copy_targets) or '(none)'}\n")
    sections.append(f"- **EXEC SQL blocks:** {len(exec_sql_blocks)}\n")
    if iria is not None:
        iria_path, _ = iria
        sections.append(
            f"- **Iria runtime contract:** present "
            f"(`{iria_path.relative_to(repo_root)}`) — file org, encoding, abend semantics, "
            "and field layout are AUTHORITATIVE; do not re-derive from COBOL text\n"
        )
    else:
        sections.append(
            "- **Iria runtime contract:** absent for this slice — persona MUST derive file org / "
            "encoding / abend semantics from the COBOL SELECT + FD + CALL statements directly\n"
        )
    sections.append("\n---\n")

    if iria is not None:
        sections.extend(_render_iria_contract(*iria, repo_root=repo_root))

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

    # Golden-master oracle: the load-bearing T2-equivalence anchor for test-author.
    # `program_name` + `repo_root` were resolved at the top of build() for the iria lookup.
    expected_output_path = repo_root / "golden-outputs" / f"{program_name}.expected-output.txt"
    if expected_output_path.exists():
        sections.append("\n---\n## Curated expected-output (T2-equivalence oracle)\n")
        sections.append(
            f"Hand-curated expected stdout for `{program_name}` when run against the canonical fixture. "
            "Load-bearing oracle for `@Tag(\"T2-equivalence\")` tests — assertions must reference this file, "
            "not inline string literals.\n\n"
        )
        sections.append(f"- **Path:** `golden-outputs/{program_name}.expected-output.txt`\n")
        expected_content = _read_truncated(expected_output_path, max_lines=200)
        sections.append(f"```text\n{expected_content}\n```\n\n")
    else:
        sections.append("\n---\n## Curated expected-output\n")
        sections.append(
            f"_(no `golden-outputs/{program_name}.expected-output.txt` found. "
            "T2-equivalence tests will not have a curated oracle for this slice; "
            "the test-author should derive postconditions from the fixture data directly and mark them as best-effort.)_\n"
        )

    # Schema reference: code-author and test-author both must emit contracts that validate.
    schema_path = repo_root / "schemas" / "public-contract.schema.json"
    if schema_path.exists():
        sections.append("\n---\n## Public-contract schema reference\n")
        sections.append(
            "Both `code-author` and `test-author` MUST emit a `public-contract.json` block that validates "
            "against this schema. Canonical-form rules (sorted arrays, normalized signatures, etc.) "
            "are enforced by `harness/contract/validate.py`.\n\n"
        )
        sections.append(f"- **Path:** `schemas/public-contract.schema.json`\n")
        sections.append("- **Top-level required fields:** `slice`, `generated_by`, `generation_run_id`, `source_anchor`, `classes`, `ports`\n")
        sections.append("- **`generated_by` values:** `\"code-author\" | \"test-author\" | \"kvote-majority\" | \"reverse-translator-roundtrip\"`\n")

    out = cfg.artifacts_dir / run_id / "context_pack.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(sections))
    return out
