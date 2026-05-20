"""Reverse-translation oracle (Determinism Stack #8).

Hand the generated Java to the [reverse-translator persona](prompts/reverse-translator.md),
get back a structurally-reconstructed COBOL, and diff against the original.

Missing elements in the back-translation = forward translation lost information
(`T2-REVERSE-DIVERGENCE`). Extra elements = forward translation hallucinated
(`T2-REVERSE-OVER-HELPFUL`). Both are real bugs the Investigator triages.

The structural diff (pure) compares:
- Set of PROCEDURE DIVISION paragraph names (case-normalized)
- Set of FILE STATUS literal values branched on
- Set of EXEC SQL block textual contents (whitespace-normalized)
- Set of DISPLAY statement targets

Orchestration (calling the reverse-translator persona) is thin and goes
through the Coordinator. The deterministic part is `structural_diff_cobol`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harness.extract.cobol_facts import CobolFacts, extract


@dataclass
class ReverseDiff:
    paragraphs_missing: list[str] = field(default_factory=list)
    paragraphs_extra: list[str] = field(default_factory=list)
    file_status_missing: list[str] = field(default_factory=list)
    file_status_extra: list[str] = field(default_factory=list)
    exec_sql_missing: list[str] = field(default_factory=list)
    exec_sql_extra: list[str] = field(default_factory=list)
    displays_missing: list[str] = field(default_factory=list)
    displays_extra: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any([
            self.paragraphs_missing, self.paragraphs_extra,
            self.file_status_missing, self.file_status_extra,
            self.exec_sql_missing, self.exec_sql_extra,
            self.displays_missing, self.displays_extra,
        ])

    def divergence_findings(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self.paragraphs_missing:
            out.append({
                "code": "T2-REVERSE-DIVERGENCE",
                "facet": "paragraphs",
                "missing": self.paragraphs_missing,
            })
        if self.file_status_missing:
            out.append({
                "code": "T2-REVERSE-DIVERGENCE",
                "facet": "file_status_codes",
                "missing": self.file_status_missing,
            })
        if self.exec_sql_missing:
            out.append({
                "code": "T2-REVERSE-DIVERGENCE",
                "facet": "exec_sql_blocks",
                "missing": self.exec_sql_missing,
            })
        if self.displays_missing:
            out.append({
                "code": "T2-REVERSE-DIVERGENCE",
                "facet": "display_statements",
                "missing": self.displays_missing,
            })
        return out

    def over_helpful_findings(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self.paragraphs_extra:
            out.append({
                "code": "T2-REVERSE-OVER-HELPFUL",
                "facet": "paragraphs",
                "extra": self.paragraphs_extra,
            })
        if self.file_status_extra:
            out.append({
                "code": "T2-REVERSE-OVER-HELPFUL",
                "facet": "file_status_codes",
                "extra": self.file_status_extra,
            })
        if self.exec_sql_extra:
            out.append({
                "code": "T2-REVERSE-OVER-HELPFUL",
                "facet": "exec_sql_blocks",
                "extra": self.exec_sql_extra,
            })
        if self.displays_extra:
            out.append({
                "code": "T2-REVERSE-OVER-HELPFUL",
                "facet": "display_statements",
                "extra": self.displays_extra,
            })
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "paragraphs_missing": self.paragraphs_missing,
            "paragraphs_extra": self.paragraphs_extra,
            "file_status_missing": self.file_status_missing,
            "file_status_extra": self.file_status_extra,
            "exec_sql_missing": self.exec_sql_missing,
            "exec_sql_extra": self.exec_sql_extra,
            "displays_missing": self.displays_missing,
            "displays_extra": self.displays_extra,
            "divergence_findings": self.divergence_findings(),
            "over_helpful_findings": self.over_helpful_findings(),
        }


def structural_diff_cobol(original: CobolFacts, reversed_facts: CobolFacts) -> ReverseDiff:
    """Compare two CobolFacts objects structurally. Pure function."""
    out = ReverseDiff()

    orig_paragraphs = {n.upper() for n, _ in original.paragraphs}
    rev_paragraphs = {n.upper() for n, _ in reversed_facts.paragraphs}
    out.paragraphs_missing = sorted(orig_paragraphs - rev_paragraphs)
    out.paragraphs_extra = sorted(rev_paragraphs - orig_paragraphs)

    orig_status = set(original.file_status_codes)
    rev_status = set(reversed_facts.file_status_codes)
    out.file_status_missing = sorted(orig_status - rev_status)
    out.file_status_extra = sorted(rev_status - orig_status)

    orig_sql = {b.text for b in original.exec_sql_blocks}
    rev_sql = {b.text for b in reversed_facts.exec_sql_blocks}
    out.exec_sql_missing = sorted(orig_sql - rev_sql)
    out.exec_sql_extra = sorted(rev_sql - orig_sql)

    # DISPLAY targets normalized: strip quotes, collapse whitespace.
    def _norm_display(targets: list[tuple[str, int]]) -> set[str]:
        return {_normalize_display(t) for t, _ in targets}

    orig_disp = _norm_display(original.display_statements)
    rev_disp = _norm_display(reversed_facts.display_statements)
    out.displays_missing = sorted(orig_disp - rev_disp)
    out.displays_extra = sorted(rev_disp - orig_disp)
    return out


def _normalize_display(target: str) -> str:
    import re
    target = target.strip()
    # Strip leading 'DISPLAY' if accidentally captured
    target = re.sub(r"^DISPLAY\s+", "", target, flags=re.IGNORECASE)
    # Collapse whitespace
    target = re.sub(r"\s+", " ", target)
    # Lowercase outside string literals (rough)
    return target.lower()


def build_reverse_input_context(java_files: dict[str, str], program_id: str) -> str:
    """Construct the Context Pack the reverse-translator persona receives.

    Per `prompts/reverse-translator.md`, the persona MUST NOT see the original COBOL —
    only the Java files + the PROGRAM-ID + DIVISION skeleton.
    """
    sections: list[str] = []
    sections.append("# Reverse-translation Context Pack\n")
    sections.append(f"- **PROGRAM-ID:** `{program_id}`\n")
    sections.append("- **Required divisions:** IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE\n")
    sections.append(
        "Reconstruct the COBOL program that the Java module below was translated from. "
        "Do not aim for byte-equality with the original; aim for structural fidelity (same paragraphs, "
        "same FILE STATUS branches, same EXEC SQL textual content, same DISPLAY target order). See "
        "`prompts/reverse-translator.md` for the full contract.\n"
    )
    sections.append("---\n## Java module\n")
    for path, body in sorted(java_files.items()):
        sections.append(f"### `{path}`\n```java\n{body}\n```\n\n")
    return "".join(sections)
