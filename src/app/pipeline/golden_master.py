"""F4 — derive golden master assertions from documented sources (no runtime).

Strategy (multi-angle, per KNOWLEDGE.md):
1. Parse JCL → discover input/output dataset names + DD statements.
2. Parse DDL → discover table schemas + constraints (NOT NULL, FKs, PKs).
3. Parse README → extract bulleted feature statements as natural-language assertions.
4. Cross-reference: combine all three into a unified `golden_master.json` with assertions.

This phase produces NO runtime captures. Runtime is out of scope.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.schemas import GoldenMaster, GoldenMasterAssertion, RunConfig


def _parse_jcl_dd_statements(jcl_text: str) -> list[dict[str, str]]:
    """Find //NAME DD DSN=... statements. Returns list of dicts with name + dsn."""
    pattern = re.compile(
        r"^//(\w+)\s+DD\s+(?:.*?DSN=([\w\.\-]+))",
        re.IGNORECASE | re.MULTILINE,
    )
    return [{"name": m.group(1), "dsn": m.group(2)} for m in pattern.finditer(jcl_text)]


def _parse_ddl_tables(ddl_text: str) -> list[dict[str, str]]:
    """Very loose DDL table extractor — just for naming, not full parsing."""
    tables = []
    for m in re.finditer(
        r"CREATE\s+TABLE\s+([\w\.]+)\s*\((.*?)\);",
        ddl_text,
        re.IGNORECASE | re.DOTALL,
    ):
        tables.append({"name": m.group(1), "columns_raw": m.group(2).strip()})
    return tables


def _parse_readme_features(readme_text: str) -> list[str]:
    """Bullet points under a 'Features' or 'Functions' section."""
    out: list[str] = []
    in_features = False
    for line in readme_text.splitlines():
        if re.match(r"^#+\s*(features|functions|usage)", line, re.IGNORECASE):
            in_features = True
            continue
        if line.startswith("#"):
            in_features = False
        if in_features and (line.lstrip().startswith("-") or line.lstrip().startswith("*")):
            out.append(line.lstrip().lstrip("-*").strip())
    return out


def build(cfg: RunConfig, run_id: str, source_file: Path) -> Path:
    """Produce `artifacts/<run_id>/golden_master.json`."""
    sub_app_root = source_file.parent.parent
    jcl_dir = sub_app_root / "jcl"
    ddl_dir = sub_app_root / "ddl"
    readme = sub_app_root / "README.md"

    assertions: list[GoldenMasterAssertion] = []

    # JCL-derived assertions: "given input dataset X and output Y, ..."
    if jcl_dir.exists():
        for f in sorted(jcl_dir.iterdir()):
            for dd in _parse_jcl_dd_statements(f.read_text(errors="replace")):
                assertions.append(GoldenMasterAssertion(
                    name=f"jcl-{f.stem}-dd-{dd['name']}",
                    description=f"JCL `{f.name}` wires DD `{dd['name']}` → DSN `{dd['dsn']}`",
                    kind="batch_output",
                    expected_output={"dd": dd["name"], "dsn": dd["dsn"]},
                ))

    # DDL-derived assertions: table presence + columns
    if ddl_dir.exists():
        for f in sorted(ddl_dir.iterdir()):
            for tbl in _parse_ddl_tables(f.read_text(errors="replace")):
                assertions.append(GoldenMasterAssertion(
                    name=f"ddl-table-{tbl['name']}",
                    description=f"Table `{tbl['name']}` defined in `{f.name}`",
                    kind="batch_output",
                    expected_output={"table": tbl["name"]},
                ))

    # README-derived natural-language features
    if readme.exists():
        for feature in _parse_readme_features(readme.read_text(errors="replace")):
            assertions.append(GoldenMasterAssertion(
                name=f"readme-feature-{hash(feature) & 0xffff:x}",
                description=feature,
                kind="batch_output",
            ))

    gm = GoldenMaster(
        program=source_file.stem,
        source_file=source_file,
        assertions=assertions,
    )
    out = cfg.artifacts_dir / run_id / "golden_master.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(gm.model_dump(mode="json"), indent=2, default=str))
    return out
