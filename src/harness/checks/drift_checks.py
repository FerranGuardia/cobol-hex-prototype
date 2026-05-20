"""Drift-catching checks against the wave-2 observed failure tags.

Each check operates on (cobol_facts, java_tree) and produces zero or more
DriftFinding entries. The findings map 1:1 to FAILURES.md tags so the
validator can surface them with concrete artifacts attached.

Catches:
- `T2-FILE-ORG-DRIFT`: COBOL declared INDEXED/SEQUENTIAL/RELATIVE with a fixed
  record but the Java adapter reads newline-delimited text.
- `T2-ABEND-CATCHABLE`: COBOL `CALL 'CEE3xxx'` but Java throws a catchable
  RuntimeException/IllegalStateException instead of System.exit or a custom
  Error subclass.
- `T1-PATH-LEAK`: `java.nio.file.Path` / `java.io.File` / `java.net.URI`
  appears in `domain/` or `application/` class signatures.
- `T2-CHARSET-IMPLICIT`: Java does `(int) someChar` for display formatting
  without an adjacent `// charset:` comment justifying the encoding.
- `T2-DUPLICATED-OUTPUT`: best-effort lexical scan for the same string
  literal being written in both a caller and a callee on the same call chain.
  Full equivalence-fidelity check is the E2E golden-master test; this is the
  cheap pre-flight catch.

Pure module: no LLM calls. Pass in parsed CobolFacts + a list of Java file
paths/contents.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.extract.cobol_facts import CobolFacts

# Java file paths (relative under output/) that count as application-layer for hex purity checks.
_DOMAIN_OR_APP_PACKAGE = re.compile(r"/(?:domain|application)/")

# Disallowed types in domain/application layer.
_LEAKING_TYPES = ("java.nio.file.Path", "java.io.File", "java.net.URI", "java.nio.file.Paths")

# Reading-as-text primitives that violate file-org preservation when COBOL says INDEXED/SEQUENTIAL with fixed records.
_TEXT_READ_PRIMITIVES = ("BufferedReader", "readLine", "Scanner", "Files.readAllLines", "Files.lines")
_FIXED_READ_PRIMITIVES = ("InputStream", "readNBytes", "RandomAccessFile", "FileChannel", "DataInputStream.readFully")

# Cee3 abend → Java terminal-error indicators.
_TERMINAL_INDICATORS = ("System.exit", "extends Error", "AbendError", "Runtime.getRuntime().halt")
_CATCHABLE_EXCEPTIONS = ("IllegalStateException", "RuntimeException", "IllegalArgumentException")

# Charset patterns: a (int) <char-expression> conversion.
_RE_INT_CAST_OF_CHAR = re.compile(
    r"\(\s*int\s*\)\s*([a-zA-Z_][a-zA-Z0-9_]*)", re.MULTILINE
)
_RE_CHARSET_COMMENT = re.compile(r"//\s*charset:", re.IGNORECASE)


@dataclass
class DriftFinding:
    code: str            # failure tag, e.g. "T2-FILE-ORG-DRIFT"
    java_file: str       # offending Java file (relative path) or "(none)"
    cobol_anchor: str    # COBOL line range or feature this anchors to
    message: str
    severity: str = "fail"  # "fail" | "warn"


@dataclass
class DriftReport:
    findings: list[DriftFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.severity == "fail" for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "findings": [
                {
                    "code": f.code,
                    "java_file": f.java_file,
                    "cobol_anchor": f.cobol_anchor,
                    "message": f.message,
                    "severity": f.severity,
                }
                for f in self.findings
            ],
        }


def run_all(cobol_facts: CobolFacts, java_root: Path) -> DriftReport:
    """Run every drift check against (cobol_facts, java_root). Java tree under output/."""
    java_files = sorted(java_root.rglob("*.java"))
    contents: dict[str, str] = {
        str(p.relative_to(java_root)): p.read_text(errors="replace") for p in java_files
    }
    report = DriftReport()
    report.findings.extend(check_file_org_drift(cobol_facts, contents))
    report.findings.extend(check_abend_catchable(cobol_facts, contents))
    report.findings.extend(check_path_leak(contents))
    report.findings.extend(check_charset_implicit(contents))
    report.findings.extend(check_duplicated_output(contents))
    return report


# ---- T2-FILE-ORG-DRIFT ---------------------------------------------------

def check_file_org_drift(facts: CobolFacts, java_files: dict[str, str]) -> list[DriftFinding]:
    """If COBOL declares INDEXED/SEQUENTIAL/RELATIVE with a record key, Java must read fixed-length blocks."""
    drift_orgs = {"INDEXED", "SEQUENTIAL", "RELATIVE"}
    risky = [s for s in facts.selects if s.organization in drift_orgs and s.record_key != "(none)"]
    if not risky:
        return []
    out: list[DriftFinding] = []
    for path, body in java_files.items():
        # `path` is repo-relative, no leading slash. Match either "adapter/out/file/" or generic "adapter/out/".
        if "adapter/out/" not in path:
            continue
        if not any(p in body for p in _TEXT_READ_PRIMITIVES):
            continue
        # If file uses both, we trust the fixed-read primitives.
        if any(p in body for p in _FIXED_READ_PRIMITIVES):
            continue
        for s in risky:
            out.append(DriftFinding(
                code="T2-FILE-ORG-DRIFT",
                java_file=path,
                cobol_anchor=f"SELECT {s.file_name} ORGANIZATION IS {s.organization} (line {s.line_start})",
                message=(
                    f"COBOL declares `{s.file_name}` as `ORGANIZATION IS {s.organization}` "
                    f"with `RECORD KEY {s.record_key}` (fixed-width records), but "
                    f"`{path}` uses line-delimited text reads (one of: {', '.join(_TEXT_READ_PRIMITIVES)}). "
                    f"Use fixed-byte reads (`InputStream.readNBytes(RECORD_LENGTH)` or `DataInputStream.readFully`)."
                ),
            ))
    return out


# ---- T2-ABEND-CATCHABLE --------------------------------------------------

def check_abend_catchable(facts: CobolFacts, java_files: dict[str, str]) -> list[DriftFinding]:
    if not facts.abend_calls:
        return []
    out: list[DriftFinding] = []
    has_terminal_anywhere = any(
        any(t in body for t in _TERMINAL_INDICATORS) for body in java_files.values()
    )
    if has_terminal_anywhere:
        return []
    # Find files mentioning ABENDING / abend / Abend that throw catchable types.
    for path, body in java_files.items():
        if not re.search(r"(?i)abend", body):
            continue
        if not any(exc in body for exc in _CATCHABLE_EXCEPTIONS):
            continue
        for callee, line in facts.abend_calls:
            out.append(DriftFinding(
                code="T2-ABEND-CATCHABLE",
                java_file=path,
                cobol_anchor=f"CALL '{callee}' (line {line})",
                message=(
                    f"COBOL invokes terminal LE service `{callee}` at line {line} (process exits). "
                    f"`{path}` translates abend to a catchable `{_first_present(body, _CATCHABLE_EXCEPTIONS)}`. "
                    f"Use `System.exit(<code>)` or a custom `Error` subclass."
                ),
            ))
            break  # one finding per Java file is enough
    return out


# ---- T1-PATH-LEAK --------------------------------------------------------

def check_path_leak(java_files: dict[str, str]) -> list[DriftFinding]:
    out: list[DriftFinding] = []
    for path, body in java_files.items():
        if not _DOMAIN_OR_APP_PACKAGE.search("/" + path):
            continue
        for leak in _LEAKING_TYPES:
            if f"import {leak};" in body or _appears_in_signature(body, leak.split(".")[-1]):
                out.append(DriftFinding(
                    code="T1-PATH-LEAK",
                    java_file=path,
                    cobol_anchor="(architectural)",
                    message=(
                        f"`{path}` is in `domain/` or `application/` and references `{leak}` "
                        f"(filesystem types must stay in `adapter/`). "
                        f"Replace with a logical resource name (e.g., `String ddName = \"CARDFILE\"`)."
                    ),
                ))
                break  # one finding per file
    return out


# ---- T2-CHARSET-IMPLICIT -------------------------------------------------

def check_charset_implicit(java_files: dict[str, str]) -> list[DriftFinding]:
    out: list[DriftFinding] = []
    for path, body in java_files.items():
        for m in _RE_INT_CAST_OF_CHAR.finditer(body):
            window_start = max(0, m.start() - 200)
            window_end = min(len(body), m.end() + 200)
            window = body[window_start:window_end]
            if _RE_CHARSET_COMMENT.search(window):
                continue
            # Likely a numeric-cast-of-char operation. Compute line.
            line_no = body[: m.start()].count("\n") + 1
            out.append(DriftFinding(
                code="T2-CHARSET-IMPLICIT",
                java_file=path,
                cobol_anchor="(byte-value formatting)",
                message=(
                    f"`{path}:{line_no}` casts `{m.group(1)}` to int (likely for display formatting) "
                    f"without a `// charset: ASCII|EBCDIC` comment within +/- 200 chars. "
                    f"COBOL on z/OS uses EBCDIC; document the assumption."
                ),
                severity="warn",
            ))
    return out


# ---- T2-DUPLICATED-OUTPUT (best-effort) ----------------------------------

def check_duplicated_output(java_files: dict[str, str]) -> list[DriftFinding]:
    """Flag a literal string written via outputPort/writeLine more than once in the same file."""
    out: list[DriftFinding] = []
    write_pattern = re.compile(r'\b(?:writeLine|println|print)\s*\(\s*"([^"]{4,})"\s*[,)]')
    for path, body in java_files.items():
        seen: dict[str, list[int]] = {}
        for m in write_pattern.finditer(body):
            literal = m.group(1)
            line_no = body[: m.start()].count("\n") + 1
            seen.setdefault(literal, []).append(line_no)
        for literal, occurrences in seen.items():
            if len(occurrences) > 1:
                out.append(DriftFinding(
                    code="T2-DUPLICATED-OUTPUT",
                    java_file=path,
                    cobol_anchor="(stdout fidelity)",
                    message=(
                        f"`{path}` writes the literal `{literal!r}` "
                        f"{len(occurrences)} times (lines {occurrences}). "
                        f"COBOL emits each DISPLAY line once; one method should own each line in the Java call chain."
                    ),
                    severity="warn",
                ))
    return out


# ---- helpers -------------------------------------------------------------

def _appears_in_signature(body: str, simple_name: str) -> bool:
    """Heuristic: simple_name as a parameter type or return type in any method/constructor."""
    pat = re.compile(
        rf"\b{re.escape(simple_name)}\b\s+[a-zA-Z_]\w*\s*[,)]"     # SimpleName paramName, ...
        rf"|\b{re.escape(simple_name)}\b\s+[a-zA-Z_]\w*\s*\("       # SimpleName fieldName(
        rf"|public[^\n]*\b{re.escape(simple_name)}\b\s+[a-zA-Z_]\w*\s*\(",  # public Path foo(
    )
    return bool(pat.search(body))


def _first_present(body: str, candidates: tuple[str, ...]) -> str:
    for c in candidates:
        if c in body:
            return c
    return candidates[0]
