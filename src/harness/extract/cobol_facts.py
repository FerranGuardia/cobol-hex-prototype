"""Mechanical fact extraction from COBOL source (Determinism Stack #6).

Pure regex/scanner extractor — no LLM in the loop. Extracts the structural
facts that downstream T2 checks compare against the generated Java:

- COPY targets (copybook names brought in via `COPY <NAME>`)
- EXEC SQL blocks (each block's text + line range)
- PROCEDURE DIVISION paragraph names (every label at column 8)
- FILE STATUS code branches (literal status values the program checks)
- SELECT statements with their ORGANIZATION / ACCESS MODE / RECORD KEY
- CALL 'CEE3xxx' invocations (LE abend calls — terminal!)
- DISPLAY targets (literal strings displayed; used for output-line provenance)

Outputs a CobolFacts dataclass that downstream `drift_checks.py` consumes.

This is the "deterministic catches" surface the user asked for: every drift
listed in docs/COMPARISON.md is checkable mechanically from these facts plus
the Java tree, without any LLM call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExecSqlBlock:
    line_start: int
    line_end: int
    text: str            # the EXEC SQL ... END-EXEC text, normalized whitespace


@dataclass
class FileSelect:
    file_name: str       # e.g. CARDFILE-FILE
    assign_to: str       # e.g. CARDFILE
    organization: str    # INDEXED | SEQUENTIAL | RELATIVE | LINE | (unspecified)
    access_mode: str     # SEQUENTIAL | RANDOM | DYNAMIC | (unspecified)
    record_key: str      # e.g. FD-CARD-NUM | (none)
    line_start: int
    line_end: int


@dataclass
class CobolFacts:
    source_path: str
    total_lines: int
    program_id: str
    copy_targets: list[str] = field(default_factory=list)
    exec_sql_blocks: list[ExecSqlBlock] = field(default_factory=list)
    paragraphs: list[tuple[str, int]] = field(default_factory=list)  # (name, line)
    file_status_codes: list[str] = field(default_factory=list)        # literals branched on, e.g. "00", "10"
    selects: list[FileSelect] = field(default_factory=list)
    abend_calls: list[tuple[str, int]] = field(default_factory=list)  # (callee, line) e.g. ('CEE3ABD', 158)
    display_statements: list[tuple[str, int]] = field(default_factory=list)  # (target-expr, line)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "total_lines": self.total_lines,
            "program_id": self.program_id,
            "copy_targets": self.copy_targets,
            "exec_sql_blocks": [
                {"line_start": b.line_start, "line_end": b.line_end, "text": b.text}
                for b in self.exec_sql_blocks
            ],
            "paragraphs": [{"name": n, "line": l} for n, l in self.paragraphs],
            "file_status_codes": self.file_status_codes,
            "selects": [
                {
                    "file_name": s.file_name,
                    "assign_to": s.assign_to,
                    "organization": s.organization,
                    "access_mode": s.access_mode,
                    "record_key": s.record_key,
                    "line_start": s.line_start,
                    "line_end": s.line_end,
                }
                for s in self.selects
            ],
            "abend_calls": [{"callee": c, "line": l} for c, l in self.abend_calls],
            "display_statements": [{"target": t, "line": l} for t, l in self.display_statements],
        }


_RE_PROGRAM_ID = re.compile(r"^\s*PROGRAM-ID\.\s*(\S+?)\.", re.IGNORECASE | re.MULTILINE)
_RE_COPY = re.compile(r"^\s*COPY\s+([A-Z0-9_-]+)\s*\.", re.IGNORECASE | re.MULTILINE)
_RE_EXEC_SQL = re.compile(r"EXEC\s+SQL\b(.*?)END-EXEC", re.IGNORECASE | re.DOTALL)
# Paragraph: a label starting at column 8 (after 7-char sequence/blank area), uppercase letters/digits/hyphens, ending in period.
_RE_PARAGRAPH = re.compile(r"^ {7}([A-Z0-9][A-Z0-9-]*)\.\s*$", re.MULTILINE)
# FILE STATUS literal in an IF predicate, e.g. IF CARDFILE-STATUS = '00'
_RE_STATUS_LITERAL = re.compile(r"=\s*'(\d{2})'", re.MULTILINE)
# SELECT block until first period at end of statement.
_RE_SELECT = re.compile(
    r"SELECT\s+(?P<file_name>[A-Z0-9-]+)\s+ASSIGN\s+TO\s+(?P<assign_to>[A-Z0-9-]+)"
    r"(?P<rest>.*?)\.",
    re.IGNORECASE | re.DOTALL,
)
# CALL 'CEE3xxx' (LE abend services). CEE3ABD = abend. CEE3DMP = dump+abend. Any CEE3* = terminal.
_RE_CEE3 = re.compile(r"CALL\s+'(CEE3[A-Z]{3})'", re.IGNORECASE)
# DISPLAY with literal first operand
_RE_DISPLAY = re.compile(r"^\s+DISPLAY\s+(.+?)\.\s*$", re.IGNORECASE | re.MULTILINE)


def extract(source_path: Path) -> CobolFacts:
    text = source_path.read_text(errors="replace")
    lines = text.splitlines()
    facts = CobolFacts(
        source_path=str(source_path),
        total_lines=len(lines),
        program_id=_first_match(_RE_PROGRAM_ID, text, group=1, default="(unknown)").strip(),
    )
    facts.copy_targets = sorted({m.group(1).upper() for m in _RE_COPY.finditer(text)})
    facts.exec_sql_blocks = _extract_exec_sql(text)
    facts.paragraphs = _extract_paragraphs(text)
    facts.file_status_codes = sorted({m.group(1) for m in _RE_STATUS_LITERAL.finditer(text)})
    facts.selects = _extract_selects(text)
    facts.abend_calls = _extract_with_lines(_RE_CEE3, text, lambda m: m.group(1).upper())
    facts.display_statements = _extract_displays(text)
    return facts


def _extract_exec_sql(text: str) -> list[ExecSqlBlock]:
    out: list[ExecSqlBlock] = []
    for m in _RE_EXEC_SQL.finditer(text):
        line_start = text[: m.start()].count("\n") + 1
        line_end = text[: m.end()].count("\n") + 1
        body = re.sub(r"\s+", " ", m.group(0).strip())
        out.append(ExecSqlBlock(line_start=line_start, line_end=line_end, text=body))
    return out


def _extract_paragraphs(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    in_procedure_division = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        upper = line.upper()
        if "PROCEDURE DIVISION" in upper:
            in_procedure_division = True
            continue
        if not in_procedure_division:
            continue
        if "END PROGRAM" in upper:
            break
        m = _RE_PARAGRAPH.match(line)
        if m:
            name = m.group(1).upper()
            # Skip section/division labels that match the pattern
            if name in {"END", "EXIT", "STOP"}:
                continue
            out.append((name, line_no))
    return out


def _extract_selects(text: str) -> list[FileSelect]:
    out: list[FileSelect] = []
    for m in _RE_SELECT.finditer(text):
        line_start = text[: m.start()].count("\n") + 1
        line_end = text[: m.end()].count("\n") + 1
        rest = m.group("rest").upper()
        org = _grep_keyword(rest, r"ORGANIZATION\s+(?:IS\s+)?(INDEXED|SEQUENTIAL|RELATIVE|LINE\s+SEQUENTIAL)")
        access = _grep_keyword(rest, r"ACCESS\s+MODE\s+(?:IS\s+)?(SEQUENTIAL|RANDOM|DYNAMIC)")
        record_key = _grep_keyword(rest, r"RECORD\s+KEY\s+(?:IS\s+)?([A-Z0-9-]+)")
        out.append(FileSelect(
            file_name=m.group("file_name").upper(),
            assign_to=m.group("assign_to").upper(),
            organization=org or "(unspecified)",
            access_mode=access or "(unspecified)",
            record_key=record_key or "(none)",
            line_start=line_start,
            line_end=line_end,
        ))
    return out


def _extract_with_lines(pattern: re.Pattern[str], text: str, extractor) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for m in pattern.finditer(text):
        line_no = text[: m.start()].count("\n") + 1
        out.append((extractor(m), line_no))
    return out


def _extract_displays(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for m in _RE_DISPLAY.finditer(text):
        line_no = text[: m.start()].count("\n") + 1
        target = m.group(1).strip()
        # Strip trailing inline comments
        target = re.sub(r"\*>.*$", "", target).strip()
        out.append((target, line_no))
    return out


def _first_match(pattern: re.Pattern[str], text: str, *, group: int = 0, default: str = "") -> str:
    m = pattern.search(text)
    if m:
        return m.group(group)
    return default


def _grep_keyword(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None
