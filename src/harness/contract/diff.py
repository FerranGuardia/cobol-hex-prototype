"""Semantic diff between two contracts (code-author vs test-author).

Per SPEC.md §Public Contract, contract-diff is the signal we want. Agreement
means the two blind generators converged; disagreement is investigated by
the Investigator agent. The diff classifies disagreements by severity:

- `critical` — class FQCNs, public method signatures, ordered side-effects,
  port FQCNs, port external boundaries. Disagreement here means the personas
  inferred different shapes from the COBOL.
- `material` — provenance line ranges, OTel span attribute lists, ArchUnit
  assertions. Disagreement reflects different reading of the same COBOL.
- `cosmetic` — declared exception ordering when both contain the same set,
  postcondition wording differences. Generally noise; collapsed.

A diff is `T2-CONTRACT-MISMATCH` when any `critical` finding exists. The
Investigator triages.

Pure module. No I/O beyond input dicts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["critical", "material", "cosmetic"]


@dataclass
class DiffEntry:
    severity: Severity
    path: str
    code_author: Any
    test_author: Any
    message: str


@dataclass
class DiffResult:
    ok: bool                       # True iff no critical entries
    entries: list[DiffEntry] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "entries": [
                {
                    "severity": e.severity,
                    "path": e.path,
                    "code_author": e.code_author,
                    "test_author": e.test_author,
                    "message": e.message,
                }
                for e in self.entries
            ],
        }


def diff_contracts(
    code_author: dict[str, Any], test_author: dict[str, Any]
) -> DiffResult:
    entries: list[DiffEntry] = []

    # Classes — by FQCN
    code_classes = {c["fqcn"]: c for c in code_author.get("classes", []) if "fqcn" in c}
    test_classes = {c["fqcn"]: c for c in test_author.get("classes", []) if "fqcn" in c}
    for fqcn in sorted(set(code_classes) | set(test_classes)):
        if fqcn not in code_classes:
            entries.append(DiffEntry(
                severity="critical",
                path=f"classes[{fqcn}]",
                code_author=None,
                test_author=test_classes[fqcn].get("kind"),
                message=f"test-author expects class `{fqcn}` but code-author did not emit it.",
            ))
            continue
        if fqcn not in test_classes:
            entries.append(DiffEntry(
                severity="critical",
                path=f"classes[{fqcn}]",
                code_author=code_classes[fqcn].get("kind"),
                test_author=None,
                message=f"code-author emitted class `{fqcn}` but test-author did not expect it.",
            ))
            continue
        # Kind agreement
        ck, tk = code_classes[fqcn].get("kind"), test_classes[fqcn].get("kind")
        if ck != tk:
            entries.append(DiffEntry(
                severity="critical",
                path=f"classes[{fqcn}].kind",
                code_author=ck, test_author=tk,
                message=f"Class kind disagreement on `{fqcn}`.",
            ))
        # Method signatures
        cm = {m["signature"]: m for m in code_classes[fqcn].get("methods", [])}
        tm = {m["signature"]: m for m in test_classes[fqcn].get("methods", [])}
        for sig in sorted(set(cm) | set(tm)):
            if sig not in cm:
                entries.append(DiffEntry(
                    severity="critical",
                    path=f"classes[{fqcn}].methods[{sig}]",
                    code_author=None, test_author=sig,
                    message=f"test-author expects method `{sig}` but code-author did not emit it.",
                ))
                continue
            if sig not in tm:
                entries.append(DiffEntry(
                    severity="material",
                    path=f"classes[{fqcn}].methods[{sig}]",
                    code_author=sig, test_author=None,
                    message=f"code-author emitted method `{sig}` not anticipated by test-author.",
                ))
                continue
            # side_effects ordering
            cse = _normalize_side_effects(cm[sig].get("side_effects", []))
            tse = _normalize_side_effects(tm[sig].get("side_effects", []))
            if cse != tse:
                entries.append(DiffEntry(
                    severity="critical",
                    path=f"classes[{fqcn}].methods[{sig}].side_effects",
                    code_author=cse, test_author=tse,
                    message="Ordered side-effects disagree (or differ in order).",
                ))
            # provenance lines
            cp = cm[sig].get("cobol_provenance", {})
            tp = tm[sig].get("cobol_provenance", {})
            if cp.get("lines") != tp.get("lines"):
                entries.append(DiffEntry(
                    severity="material",
                    path=f"classes[{fqcn}].methods[{sig}].cobol_provenance.lines",
                    code_author=cp.get("lines"), test_author=tp.get("lines"),
                    message="Provenance line range disagreement.",
                ))

    # Ports — by FQCN
    code_ports = {p["fqcn"]: p for p in code_author.get("ports", []) if "fqcn" in p}
    test_ports = {p["fqcn"]: p for p in test_author.get("ports", []) if "fqcn" in p}
    for fqcn in sorted(set(code_ports) | set(test_ports)):
        if fqcn not in code_ports:
            entries.append(DiffEntry(
                severity="critical",
                path=f"ports[{fqcn}]",
                code_author=None, test_author=test_ports[fqcn].get("external_boundary"),
                message=f"test-author expects port `{fqcn}` but code-author did not emit it.",
            ))
            continue
        if fqcn not in test_ports:
            entries.append(DiffEntry(
                severity="critical",
                path=f"ports[{fqcn}]",
                code_author=code_ports[fqcn].get("external_boundary"), test_author=None,
                message=f"code-author emitted port `{fqcn}` but test-author did not expect it.",
            ))
            continue
        cb, tb = code_ports[fqcn].get("external_boundary"), test_ports[fqcn].get("external_boundary")
        if cb != tb:
            entries.append(DiffEntry(
                severity="critical",
                path=f"ports[{fqcn}].external_boundary",
                code_author=cb, test_author=tb,
                message="Port external_boundary disagrees.",
            ))
        cj, tj = code_ports[fqcn].get("justification"), test_ports[fqcn].get("justification")
        if cj != tj:
            entries.append(DiffEntry(
                severity="material",
                path=f"ports[{fqcn}].justification",
                code_author=cj, test_author=tj,
                message="Port justification disagrees.",
            ))

    summary = {
        "critical": sum(1 for e in entries if e.severity == "critical"),
        "material": sum(1 for e in entries if e.severity == "material"),
        "cosmetic": sum(1 for e in entries if e.severity == "cosmetic"),
        "total": len(entries),
    }
    return DiffResult(ok=summary["critical"] == 0, entries=entries, summary=summary)


def _normalize_side_effects(side_effects: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Reduce a side_effect list to a comparable canonical form preserving order."""
    out: list[tuple[Any, ...]] = []
    for se in side_effects:
        kind = se.get("kind")
        if kind == "port-call":
            out.append((kind, se.get("port"), se.get("method"), se.get("ordering")))
        elif kind == "stdout":
            out.append((kind, se.get("target"), se.get("ordering")))
        elif kind == "file-write":
            out.append((kind, se.get("path"), se.get("ordering")))
        elif kind == "sql-execute":
            out.append((kind, se.get("statement_class"), se.get("table"), se.get("ordering")))
        elif kind == "state-mutation":
            out.append((kind, se.get("state_field"), se.get("from"), se.get("to"), se.get("ordering")))
        else:
            out.append((kind, str(sorted(se.items()))))
    return out
