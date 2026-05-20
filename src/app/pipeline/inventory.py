"""F1 — static scan of the corpus. No LLM calls."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app.core.schemas import Inventory, InventoryEntry, RunConfig

# Heuristic complexity weights (mirrors Azure repo's COBOL complexity scoring).
COMPLEXITY_PATTERNS: dict[str, int] = {
    r"\bEXEC\s+SQL\b": 3,
    r"\bEXEC\s+CICS\b": 4,
    r"\bEXEC\s+DLI\b": 4,
    r"\bEXEC\s+MQ\b": 4,
    r"\bPERFORM\s+VARYING\b": 2,
    r"\bPERFORM\s+UNTIL\b": 1,
    r"\bEVALUATE\s+TRUE\b": 2,
    r"\bSEARCH\s+ALL\b": 2,
    r"\bREDEFINES\b": 2,
    r"\bOCCURS\s+\d+\s+DEPENDING\b": 3,
    r"\bUNSTRING\b": 2,
    r"\bSTRING\b": 1,
    r"\bALTER\b": 3,
    r"\bGO\s+TO\s+DEPENDING\b": 3,
    r"\bCALL\s+['\"]": 2,
    r"^\s*COPY\b": 1,
    r"\bREPLACE\b": 2,
    r"\bCOMPUTE\b": 1,
    r"\bINSPECT\b": 1,
}


def _kind_of(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    return {
        "cbl": "cbl", "cob": "cbl",
        "cpy": "cpy",
        "jcl": "jcl",
        "ddl": "ddl",
        "dcl": "dcl",
        "bms": "bms",
        "ctl": "ctl",
        "csd": "csd",
    }.get(ext, "other")


def _complexity(text: str) -> int:
    score = 0
    for pattern, weight in COMPLEXITY_PATTERNS.items():
        score += weight * len(re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE))
    # density bonuses (mirrors Azure approach)
    lines = text.splitlines() or [""]
    pic_density = sum(1 for ln in lines if "PIC " in ln.upper() or " PIC(" in ln.upper())
    if pic_density / max(len(lines), 1) > 0.25:
        score += 3
    if re.search(r"\bEXEC\s+SQL\b|\bEXEC\s+DLI\b", text, re.IGNORECASE):
        score += 4
    return score


def scan(cfg: RunConfig, slice_name: str | None = None) -> Path:
    """Scan the corpus (or a sub-application slice). Emits inventory.json."""
    root = cfg.corpus_root
    if slice_name:
        roots = [root / "app" / slice_name]
    else:
        roots = [root]

    entries: list[InventoryEntry] = []
    for r in roots:
        if not r.exists():
            continue
        for path in sorted(r.rglob("*")):
            if path.is_dir():
                continue
            kind = _kind_of(path)
            if kind == "other":
                continue
            try:
                text = path.read_text(errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            lines = text.count("\n") + (0 if text.endswith("\n") else 1)
            score = _complexity(text) if kind in {"cbl", "cpy"} else 0
            sub_app = None
            if "app" in path.parts:
                idx = path.parts.index("app")
                if idx + 1 < len(path.parts):
                    sub_app = path.parts[idx + 1]
            entries.append(InventoryEntry(
                path=path.relative_to(root),
                kind=kind,  # type: ignore[arg-type]
                lines=lines,
                complexity_score=score,
                sub_application=sub_app,
            ))

    inv = Inventory(
        scanned_at=datetime.now(),
        corpus_root=root,
        slice_name=slice_name,
        entries=entries,
    )
    out = cfg.artifacts_dir / "inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inv.model_dump(mode="json"), indent=2, default=str))
    return out
