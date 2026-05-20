"""F1b — deterministic candidate triage for the COBOL corpus.

Pure stdlib. No LLM calls. No pydantic. Runnable standalone:

    python3 src/app/pipeline/candidates.py <corpus_root> [--out artifacts/]

What it produces (write-only outputs):

- `artifacts/candidates.json` — full per-file fingerprint
- `artifacts/candidates_summary.json` — corpus-level rollup (counts, tiers)

What "deterministic" means here:

1. Same bytes in → same JSON out. We sort entries by path and round floats.
2. We hash the raw file (`sha256_raw`) AND a canonicalized code-area-only
   form (`sha256_code`) that strips sequence area (cols 1-6), indicator
   col 7, the right margin (cols 73-80), and trailing whitespace. The
   second hash is invariant under cosmetic reformat (line-number renumbering,
   trailing seq-numbers, etc.) and is what we use for caching downstream.
3. Counts come from a single normalized line stream — we never look at
   the original line twice from two different regexes. Comments and blank
   lines are excluded before any pattern scan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Reusing the Azure repo's weighting philosophy: SQL/DLI/MQ/CICS dominate.
COMPLEXITY_WEIGHTS: dict[str, int] = {
    "exec_sql": 3,
    "exec_cics": 4,
    "exec_dli": 4,
    "exec_mq": 4,
    "perform_varying": 2,
    "perform_until": 1,
    "evaluate_true": 2,
    "search_all": 2,
    "redefines": 2,
    "occurs_depending": 3,
    "unstring": 2,
    "string": 1,
    "alter": 3,
    "go_to_depending": 3,
    "call_lit": 2,
    "copy": 1,
    "replace": 2,
    "compute": 1,
    "inspect": 1,
}

# Tier cutoffs (calibrate after first real run; reasonable defaults).
TIER_CUTOFFS = {"LOW": 20, "MED": 60}  # score <20 → LOW, <60 → MED, else HIGH

COBOL_EXTS = {".cbl", ".cob", ".cpy"}

PATTERN_EXEC_SQL = re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)
PATTERN_EXEC_CICS = re.compile(r"\bEXEC\s+CICS\b", re.IGNORECASE)
PATTERN_EXEC_DLI = re.compile(r"\bEXEC\s+DLI\b", re.IGNORECASE)
PATTERN_EXEC_MQ = re.compile(r"\bEXEC\s+MQ\b", re.IGNORECASE)
PATTERN_END_EXEC = re.compile(r"\bEND-EXEC\b", re.IGNORECASE)
PATTERN_PERFORM_VARYING = re.compile(r"\bPERFORM\b.*\bVARYING\b", re.IGNORECASE)
PATTERN_PERFORM_UNTIL = re.compile(r"\bPERFORM\b.*\bUNTIL\b", re.IGNORECASE)
PATTERN_PERFORM = re.compile(r"\bPERFORM\b", re.IGNORECASE)
PATTERN_EVALUATE_TRUE = re.compile(r"\bEVALUATE\s+TRUE\b", re.IGNORECASE)
PATTERN_SEARCH_ALL = re.compile(r"\bSEARCH\s+ALL\b", re.IGNORECASE)
PATTERN_REDEFINES = re.compile(r"\bREDEFINES\b", re.IGNORECASE)
PATTERN_OCCURS_DEPENDING = re.compile(r"\bOCCURS\s+\d+\s+DEPENDING\b", re.IGNORECASE)
PATTERN_UNSTRING = re.compile(r"\bUNSTRING\b", re.IGNORECASE)
PATTERN_STRING_VERB = re.compile(r"(?<![-\w])STRING\b(?!-)", re.IGNORECASE)
PATTERN_ALTER = re.compile(r"\bALTER\b", re.IGNORECASE)
PATTERN_GO_TO_DEPENDING = re.compile(r"\bGO\s+TO\b.*\bDEPENDING\b", re.IGNORECASE)
PATTERN_GO_TO = re.compile(r"\bGO\s+TO\b", re.IGNORECASE)
PATTERN_CALL_LIT = re.compile(r"\bCALL\s+['\"]([A-Z0-9_-]+)['\"]", re.IGNORECASE)
PATTERN_CALL_CBLTDLI = re.compile(r"\bCALL\s+['\"]CBLTDLI['\"]", re.IGNORECASE)
PATTERN_CALL_MQ = re.compile(r"\bCALL\s+['\"]MQ(OPEN|CLOSE|GET|PUT|PUT1|CONN|CONNX|DISC|INQ|SET|CMIT|BACK|SUB)['\"]", re.IGNORECASE)
PATTERN_COPY = re.compile(r"\bCOPY\s+([A-Z0-9_-]+)", re.IGNORECASE)
PATTERN_REPLACE = re.compile(r"\bREPLACE\b", re.IGNORECASE)
PATTERN_COMPUTE = re.compile(r"\bCOMPUTE\b", re.IGNORECASE)
PATTERN_INSPECT = re.compile(r"\bINSPECT\b", re.IGNORECASE)
PATTERN_PROGRAM_ID = re.compile(r"\bPROGRAM-ID\.?\s+([A-Z0-9_-]+)", re.IGNORECASE)
PATTERN_SECTION = re.compile(r"^\s*([A-Z0-9][A-Z0-9-]*)\s+SECTION\s*\.\s*$", re.IGNORECASE)
PATTERN_PARAGRAPH = re.compile(r"^([A-Z0-9][A-Z0-9-]*)\s*\.\s*$", re.IGNORECASE)

# Lines that start a DIVISION header — we skip these when counting paragraphs.
DIVISIONS = {"IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE"}


@dataclass
class FileFingerprint:
    path: str  # relative to corpus_root
    name: str
    ext: str
    sub_application: str | None
    bytes: int
    sha256_raw: str
    sha256_code: str
    lines_raw: int
    lines_code: int  # non-comment, non-blank, after column normalization
    lines_comment: int
    program_id: str | None
    section_count: int
    paragraph_count: int
    copy_names: list[str]
    call_targets: list[str]
    counts: dict[str, int] = field(default_factory=dict)
    complexity_score: int = 0
    tier: str = "LOW"
    eligibility: str = "in_scope"  # in_scope | out_of_scope
    out_of_scope_reasons: list[str] = field(default_factory=list)


def _strip_columns(line: str) -> tuple[str, str]:
    """Return (indicator_char, code_area) for a fixed-format COBOL line.

    Cols 1-6: sequence (ignored). Col 7: indicator. Cols 8-72: code area.
    Cols 73-80: identification area (ignored).
    If the line is too short (e.g. free-format), col 7 = " " and code_area
    = the whole line.
    """
    # Strip trailing newline only; do not lstrip — column positions matter.
    line = line.rstrip("\n").rstrip("\r")
    if len(line) < 7:
        return " ", line.lstrip()
    indicator = line[6]
    code_area = line[7:72] if len(line) > 7 else ""
    return indicator, code_area.rstrip()


def _canonicalize(text: str) -> tuple[str, list[str], int]:
    """Strip sequence + indicator + right-margin from each line.

    Returns (canonical_text, code_lines, comment_count).
    Comment lines (indicator = `*` or `/`) are dropped from the canonical
    form so the hash is stable under comment edits.
    """
    canonical_lines: list[str] = []
    code_lines: list[str] = []
    comments = 0
    for raw in text.splitlines():
        indicator, code = _strip_columns(raw)
        if indicator in ("*", "/"):
            comments += 1
            continue
        if not code.strip():
            continue
        canonical_lines.append(code)
        code_lines.append(code)
    return "\n".join(canonical_lines) + "\n", code_lines, comments


def _count(pattern: re.Pattern, text: str) -> int:
    return len(pattern.findall(text))


def _sub_application(path: Path, corpus_root: Path) -> str | None:
    """Infer the sub-application from the relative path."""
    try:
        rel = path.relative_to(corpus_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "app":
        # Either `app/<sub-app>/...` or `app/<bucket>/file.cbl` (no sub-app).
        candidate = parts[1]
        if candidate.startswith("app-"):
            return candidate
        return None
    return None


def fingerprint(path: Path, corpus_root: Path) -> FileFingerprint:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    canonical, code_lines, comment_count = _canonicalize(text)
    code_text = "\n".join(code_lines)

    counts = {
        "exec_sql": _count(PATTERN_EXEC_SQL, code_text),
        "exec_cics": _count(PATTERN_EXEC_CICS, code_text),
        "exec_dli": _count(PATTERN_EXEC_DLI, code_text),
        "exec_mq": _count(PATTERN_EXEC_MQ, code_text),
        "end_exec": _count(PATTERN_END_EXEC, code_text),
        "perform_varying": _count(PATTERN_PERFORM_VARYING, code_text),
        "perform_until": _count(PATTERN_PERFORM_UNTIL, code_text),
        "perform_total": _count(PATTERN_PERFORM, code_text),
        "evaluate_true": _count(PATTERN_EVALUATE_TRUE, code_text),
        "search_all": _count(PATTERN_SEARCH_ALL, code_text),
        "redefines": _count(PATTERN_REDEFINES, code_text),
        "occurs_depending": _count(PATTERN_OCCURS_DEPENDING, code_text),
        "unstring": _count(PATTERN_UNSTRING, code_text),
        "string": _count(PATTERN_STRING_VERB, code_text),
        "alter": _count(PATTERN_ALTER, code_text),
        "go_to_depending": _count(PATTERN_GO_TO_DEPENDING, code_text),
        "go_to_total": _count(PATTERN_GO_TO, code_text),
        "call_lit": _count(PATTERN_CALL_LIT, code_text),
        "call_cbltdli": _count(PATTERN_CALL_CBLTDLI, code_text),
        "call_mq": _count(PATTERN_CALL_MQ, code_text),
        "copy": _count(PATTERN_COPY, code_text),
        "replace": _count(PATTERN_REPLACE, code_text),
        "compute": _count(PATTERN_COMPUTE, code_text),
        "inspect": _count(PATTERN_INSPECT, code_text),
    }

    program_id_match = PATTERN_PROGRAM_ID.search(code_text)
    program_id = program_id_match.group(1).upper() if program_id_match else None

    section_count = sum(1 for ln in code_lines if PATTERN_SECTION.match(ln))
    paragraph_count = 0
    for ln in code_lines:
        m = PATTERN_PARAGRAPH.match(ln)
        if not m:
            continue
        head = m.group(1).upper()
        if head in DIVISIONS:
            continue
        if head.endswith("SECTION"):
            continue
        paragraph_count += 1
    # Sections are also paragraph-shaped; subtract to avoid double-counting.
    paragraph_count = max(0, paragraph_count - section_count)

    copy_names = sorted({m.group(1).upper() for m in PATTERN_COPY.finditer(code_text)})
    call_targets = sorted({m.group(1).upper() for m in PATTERN_CALL_LIT.finditer(code_text)})

    score = sum(COMPLEXITY_WEIGHTS[k] * counts[k] for k in COMPLEXITY_WEIGHTS)
    if score < TIER_CUTOFFS["LOW"]:
        tier = "LOW"
    elif score < TIER_CUTOFFS["MED"]:
        tier = "MED"
    else:
        tier = "HIGH"

    # Eligibility under step-1 scope: COBOL-only, DB2-batch, no CICS/IMS/MQ.
    reasons: list[str] = []
    if counts["exec_cics"] > 0:
        reasons.append("EXEC CICS (online)")
    if counts["exec_dli"] > 0:
        reasons.append("EXEC DLI (IMS)")
    if counts["exec_mq"] > 0:
        reasons.append("EXEC MQ")
    if counts["call_cbltdli"] > 0:
        reasons.append("CALL 'CBLTDLI' (IMS via batch CALL interface)")
    if counts["call_mq"] > 0:
        reasons.append("CALL 'MQ*' (MQ batch CALL interface)")
    if counts["alter"] > 0:
        reasons.append("ALTER (dynamic GO TO target)")
    if counts["go_to_depending"] > 0:
        reasons.append("GO TO ... DEPENDING ON (computed GOTO)")
    eligibility = "in_scope" if not reasons else "out_of_scope"

    return FileFingerprint(
        path=str(path.relative_to(corpus_root)),
        name=path.name,
        ext=path.suffix.lower(),
        sub_application=_sub_application(path, corpus_root),
        bytes=len(raw),
        sha256_raw=hashlib.sha256(raw).hexdigest(),
        sha256_code=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        lines_raw=text.count("\n") + (0 if text.endswith("\n") else 1),
        lines_code=len(code_lines),
        lines_comment=comment_count,
        program_id=program_id,
        section_count=section_count,
        paragraph_count=paragraph_count,
        copy_names=copy_names,
        call_targets=call_targets,
        counts=counts,
        complexity_score=score,
        tier=tier,
        eligibility=eligibility,
        out_of_scope_reasons=reasons,
    )


def discover_files(corpus_root: Path) -> list[Path]:
    files: list[Path] = []
    for p in corpus_root.rglob("*"):
        if p.is_dir():
            continue
        if p.suffix.lower() in COBOL_EXTS:
            files.append(p)
    files.sort()  # determinism
    return files


def summarize(fps: list[FileFingerprint]) -> dict:
    by_ext: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_eligibility: dict[str, int] = {}
    by_sub_app: dict[str, dict[str, int]] = {}
    for fp in fps:
        by_ext[fp.ext] = by_ext.get(fp.ext, 0) + 1
        by_tier[fp.tier] = by_tier.get(fp.tier, 0) + 1
        by_eligibility[fp.eligibility] = by_eligibility.get(fp.eligibility, 0) + 1
        sa = fp.sub_application or "(root)"
        bucket = by_sub_app.setdefault(sa, {"total": 0, "in_scope": 0, "cbl": 0, "cpy": 0})
        bucket["total"] += 1
        if fp.eligibility == "in_scope":
            bucket["in_scope"] += 1
        if fp.ext in (".cbl", ".cob"):
            bucket["cbl"] += 1
        if fp.ext == ".cpy":
            bucket["cpy"] += 1
    in_scope_cbl = [fp for fp in fps if fp.eligibility == "in_scope" and fp.ext in (".cbl", ".cob")]
    in_scope_cbl_sorted = sorted(in_scope_cbl, key=lambda f: (f.complexity_score, f.lines_code))
    ranked = [
        {
            "path": fp.path,
            "program_id": fp.program_id,
            "lines_code": fp.lines_code,
            "complexity_score": fp.complexity_score,
            "tier": fp.tier,
            "exec_sql": fp.counts.get("exec_sql", 0),
            "copy_names": fp.copy_names,
        }
        for fp in in_scope_cbl_sorted
    ]
    return {
        "totals": {"files": len(fps), **by_ext},
        "by_tier": by_tier,
        "by_eligibility": by_eligibility,
        "by_sub_application": by_sub_app,
        "in_scope_cbl_ranked": ranked,
    }


def write_outputs(
    fps: list[FileFingerprint],
    out_dir: Path,
    corpus_root: Path,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    fps_sorted = sorted(fps, key=lambda f: f.path)
    payload = {
        "schema_version": "v1",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "corpus_root": str(corpus_root),
        "entries": [asdict(fp) for fp in fps_sorted],
    }
    candidates_path = out_dir / "candidates.json"
    candidates_path.write_text(json.dumps(payload, indent=2, sort_keys=False))
    summary_path = out_dir / "candidates_summary.json"
    summary_path.write_text(json.dumps(summarize(fps_sorted), indent=2, sort_keys=False))
    return candidates_path, summary_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic COBOL candidate triage.")
    parser.add_argument("corpus_root", type=Path, help="Path to CardDemo (or any corpus root).")
    parser.add_argument("--out", type=Path, default=Path("artifacts"), help="Output directory.")
    args = parser.parse_args(argv)
    if not args.corpus_root.exists():
        print(f"corpus root not found: {args.corpus_root}", file=sys.stderr)
        return 2
    files = discover_files(args.corpus_root)
    if not files:
        print(f"no COBOL files found under {args.corpus_root}", file=sys.stderr)
        return 1
    fps = [fingerprint(p, args.corpus_root) for p in files]
    cpath, spath = write_outputs(fps, args.out, args.corpus_root)
    print(f"candidates: {cpath}")
    print(f"summary:    {spath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
