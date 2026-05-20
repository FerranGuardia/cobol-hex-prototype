"""Contract schema + canonical-form validation (Determinism Stack #3).

Validates a generated public-contract.json against:
1. The strict JSON Schema at schemas/public-contract.schema.json.
2. The canonical-form rules in SPEC.md §Canonical form (sorted arrays,
   normalized signatures, lowercase SHA, etc).

If anything fails, emit a `retry_prompt` field with concrete corrections that
the retry-loop driver appends to the next persona invocation.

Pure module: no Codex orchestration. The retry-loop driver lives in the F5
two-pass orchestrator (next iteration) and calls into this module.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

# repo_root = .../cobol-hex-prototype
SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "schemas" / "public-contract.schema.json"
)

# Identity field per array-of-objects path; used by the sorted-array canonical check.
ARRAY_KEY: dict[str, str] = {
    "classes": "fqcn",
    "ports": "fqcn",
    "archunit_assertions": "rule",
    "classes[].methods": "signature",
    "ports[].methods": "signature",
}

# JLS modifier order used by the signature canonical-form check.
JLS_MODIFIER_ORDER: tuple[str, ...] = (
    "public", "protected", "private",
    "static", "final", "abstract", "default", "synchronized", "native", "strictfp",
)


@dataclass
class ValidationFinding:
    code: str           # T1-SCHEMA-INVALID, T1-NON-CANONICAL-ARRAY, etc.
    path: str           # JSON path of the violation
    message: str        # human-readable description


@dataclass
class ValidationResult:
    ok: bool
    findings: list[ValidationFinding] = field(default_factory=list)
    retry_prompt: str = ""
    schema_errors: int = 0
    canonical_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "schema_errors": self.schema_errors,
            "canonical_errors": self.canonical_errors,
            "findings": [
                {"code": f.code, "path": f.path, "message": f.message}
                for f in self.findings
            ],
            "retry_prompt": self.retry_prompt,
        }


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


def validate(contract: dict[str, Any]) -> ValidationResult:
    """Run schema + canonical checks. Return structured findings.

    Never raises on bad input: any unexpected type inside the contract becomes
    a `T1-VALIDATOR-INTERNAL` finding so the caller's retry loop can still
    proceed instead of crashing the whole persona-call.
    """
    findings: list[ValidationFinding] = []

    if not isinstance(contract, dict):
        return ValidationResult(
            ok=False,
            findings=[ValidationFinding(
                code="T1-SCHEMA-INVALID",
                path="<root>",
                message=f"contract is {type(contract).__name__}, expected object",
            )],
            schema_errors=1,
            canonical_errors=0,
            retry_prompt="The contract must be a JSON object.",
        )

    schema = load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    schema_errors = sorted(
        validator.iter_errors(contract), key=lambda e: list(e.absolute_path)
    )
    for err in schema_errors:
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        findings.append(
            ValidationFinding(code="T1-SCHEMA-INVALID", path=path, message=err.message)
        )

    # Canonical form: belt-and-suspenders try/except so a surprise input shape
    # doesn't take down the whole convert loop. If the schema check already
    # caught it, we still get coverage; if it didn't, we surface a self-describing
    # finding instead of a raw traceback.
    try:
        canonical_findings = _check_canonical(contract)
    except Exception as exc:  # pragma: no cover — defensive
        canonical_findings = [ValidationFinding(
            code="T1-VALIDATOR-INTERNAL",
            path="<root>",
            message=f"canonical check raised {exc.__class__.__name__}: {exc}",
        )]
    findings.extend(canonical_findings)

    ok = not findings
    return ValidationResult(
        ok=ok,
        findings=findings,
        schema_errors=len(schema_errors),
        canonical_errors=len(canonical_findings),
        retry_prompt=_build_retry_prompt(findings) if not ok else "",
    )


def _check_canonical(contract: dict[str, Any]) -> list[ValidationFinding]:
    out: list[ValidationFinding] = []

    for arr_path, key in ARRAY_KEY.items():
        items = _get_array(contract, arr_path)
        if items is None:
            continue
        keys = [str(it.get(key, "")) for it in items]
        if keys != sorted(keys):
            out.append(ValidationFinding(
                code="T1-NON-CANONICAL-ARRAY",
                path=arr_path,
                message=f"Array `{arr_path}` not sorted by `{key}`. Expected: {sorted(keys)}. Got: {keys}.",
            ))

    for cls_idx, cls in enumerate(contract.get("classes", []) or []):
        if not isinstance(cls, dict):
            continue
        for m_idx, m in enumerate(cls.get("methods", []) or []):
            if not isinstance(m, dict):
                continue
            sig = m.get("signature", "")
            err = _check_signature_canonical(sig)
            if err:
                out.append(ValidationFinding(
                    code="T1-NON-CANONICAL-SIGNATURE",
                    path=f"classes[{cls_idx}].methods[{m_idx}].signature",
                    message=f"`{sig}`: {err}",
                ))
            prov = m.get("cobol_provenance") or {}
            lines = prov.get("lines", "") if isinstance(prov, dict) else ""
            if lines and not re.match(r"^\d+-\d+$", lines):
                out.append(ValidationFinding(
                    code="T1-NON-CANONICAL-LINE-RANGE",
                    path=f"classes[{cls_idx}].methods[{m_idx}].cobol_provenance.lines",
                    message=f"Line range must be `start-end` with no spaces: {lines!r}",
                ))

    sa = contract.get("source_anchor", {})
    # Schema requires source_anchor to be an object; defend against personas
    # that emit it as a list/string anyway — surface as canonical finding rather
    # than crashing the validate-and-retry loop.
    if not isinstance(sa, dict):
        out.append(ValidationFinding(
            code="T1-NON-CANONICAL-SOURCE-ANCHOR",
            path="source_anchor",
            message=(
                f"source_anchor must be a JSON object with `cobol_path` + `cobol_sha256`, "
                f"got {type(sa).__name__}"
            ),
        ))
        return out

    for k in ("cobol_sha256",):
        v = sa.get(k)
        if v and not _is_lowercase_sha256(v):
            out.append(ValidationFinding(
                code="T1-NON-CANONICAL-SHA",
                path=f"source_anchor.{k}",
                message=f"Not lowercase hex SHA-256: {v!r}",
            ))
    for k in ("cobol_path",):
        v = sa.get(k, "")
        if isinstance(v, str) and "\\" in v:
            out.append(ValidationFinding(
                code="T1-NON-CANONICAL-PATH",
                path=f"source_anchor.{k}",
                message=f"Use Unix path separator `/`, got: {v!r}",
            ))

    return out


def _get_array(contract: dict[str, Any], path: str) -> list[dict[str, Any]] | None:
    if path == "classes":
        return contract.get("classes")
    if path == "ports":
        return contract.get("ports")
    if path == "archunit_assertions":
        return contract.get("archunit_assertions")
    if path == "classes[].methods":
        return [m for cls in contract.get("classes", []) for m in cls.get("methods", [])]
    if path == "ports[].methods":
        return [m for p in contract.get("ports", []) for m in p.get("methods", [])]
    return None


def _check_signature_canonical(sig: str) -> str | None:
    if not sig:
        return None
    if re.search(r"  +", sig):
        return "contains multiple consecutive spaces"
    if re.search(r"<\s+|\s+>|\s+<", sig):
        return "generic brackets have whitespace; expected `List<String>` not `List <String>`"
    tokens = sig.split()
    mods: list[str] = []
    for t in tokens:
        if t in JLS_MODIFIER_ORDER:
            mods.append(t)
        else:
            break
    expected = [m for m in JLS_MODIFIER_ORDER if m in mods]
    if mods != expected:
        return f"modifiers out of JLS order. Expected {expected}, got {mods}"
    return None


def _is_lowercase_sha256(s: str) -> bool:
    return bool(re.match(r"^[a-f0-9]{64}$", s))


def _build_retry_prompt(findings: list[ValidationFinding]) -> str:
    lines = [
        "Your previous contract emission had validation errors. "
        "Fix ALL of them and re-emit the complete contract JSON.",
    ]
    by_code: dict[str, list[ValidationFinding]] = {}
    for f in findings:
        by_code.setdefault(f.code, []).append(f)
    for code, items in by_code.items():
        suffix = "s" if len(items) != 1 else ""
        lines.append(f"\n## {code} ({len(items)} occurrence{suffix})")
        for item in items[:10]:
            lines.append(f"  - `{item.path}`: {item.message}")
        if len(items) > 10:
            lines.append(f"  - ... and {len(items) - 10} more of the same code")
    lines.append(
        "\nRe-emit the complete contracts/public-contract.<persona>.json with all errors corrected. "
        "Do not change any value other than what is necessary to fix the errors."
    )
    return "\n".join(lines)
