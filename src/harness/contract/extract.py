"""Mechanical contract extraction from emitted Java (Determinism Stack #6, v3).

Replaces the LLM-emitted `public-contract.<persona>.json` blocks. Each persona
now writes only its primary artifact (Java code OR tests), and the harness
derives the contract from the emitted code via javalang AST. The diff signal
stays — code-author and test-author can still disagree on which classes /
methods are needed — but the production of the contract is mechanical and
free, not a 50% slice of the model's output budget.

Two entry points:

- `extract_from_code_tree(...)` — walks the code-author's emitted main-source
  tree, produces a contract describing every public class it found.
- `extract_from_test_tree(...)` — walks the test-author's emitted test tree,
  produces a contract describing every class the tests REFERENCE (via
  imports + invocations). The fqcn agreement / disagreement with the
  code-author contract is the load-bearing diff signal.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import javalang


# ---- public API -------------------------------------------------------------

def extract_from_code_tree(
    java_root: Path,
    *,
    slice_name: str,
    run_id: str,
    cobol_source: Path | None,
    copybooks: list[Path] | None = None,
    jcl: list[Path] | None = None,
    fixture: Path | None = None,
    expected_output: Path | None = None,
) -> dict[str, Any]:
    """Produce a `public-contract.json` from the emitted Java code tree.

    Walks every `*.java` under java_root, skipping the `src/test/` subtree.
    """
    classes: list[dict[str, Any]] = []
    ports: list[dict[str, Any]] = []

    for jpath in _iter_java_files(java_root, skip_tests=True):
        try:
            tree = javalang.parse.parse(jpath.read_text(errors="replace"))
        except Exception:
            continue
        package = tree.package.name if tree.package else ""
        for type_decl in tree.types or []:
            cls_dict = _build_class_dict(jpath, package, type_decl)
            if cls_dict is None:
                continue
            classes.append(cls_dict)
            if cls_dict["kind"] == "domain-port":
                ports.append(_build_port_dict(cls_dict))

    classes.sort(key=lambda c: c["fqcn"])
    ports.sort(key=lambda p: p["fqcn"])

    return {
        "slice": slice_name,
        "generated_by": "code-author-extracted",
        "generation_run_id": run_id,
        "source_anchor": _build_source_anchor(
            cobol_source, copybooks, jcl, fixture, expected_output
        ),
        "classes": classes,
        "ports": ports,
        "archunit_assertions": [],
    }


def extract_from_test_tree(
    test_root: Path,
    *,
    slice_name: str,
    run_id: str,
    cobol_source: Path | None,
    copybooks: list[Path] | None = None,
    jcl: list[Path] | None = None,
    fixture: Path | None = None,
    expected_output: Path | None = None,
) -> dict[str, Any]:
    """Produce a `public-contract.json` describing what the tests REFERENCE.

    Strategy: walk every `src/test/java/**/*.java`, parse with javalang,
    record (a) imports under the slice's expected package, (b) method calls
    against instances whose declared type is one of those imported classes.

    The resulting contract says "the tests expect a class with FQCN X and
    methods [a, b, c]" — which `diff.py` compares against what code-author
    actually emitted.
    """
    classes: dict[str, dict[str, Any]] = {}
    expected_package = f"com.example.cobol.{slice_name.lower()}"

    for jpath in _iter_java_files(test_root, only_tests=True):
        try:
            text = jpath.read_text(errors="replace")
            tree = javalang.parse.parse(text)
        except Exception:
            continue

        # Map short class names -> FQCN for everything the test imports under our slice.
        local_types: dict[str, str] = {}
        for imp in tree.imports or []:
            fqcn = imp.path
            if not fqcn.startswith(expected_package):
                continue
            short = fqcn.split(".")[-1]
            local_types[short] = fqcn
            classes.setdefault(fqcn, _empty_class_record(fqcn))

        # Map local variables -> declared type (only those in local_types).
        var_types: dict[str, str] = {}
        # Visit FieldDeclaration + LocalVariableDeclaration to capture decls.
        for _, node in tree.filter(javalang.tree.LocalVariableDeclaration):
            type_name = _type_name(node.type)
            if type_name in local_types:
                for declarator in node.declarators:
                    var_types[declarator.name] = local_types[type_name]
        for _, node in tree.filter(javalang.tree.FieldDeclaration):
            type_name = _type_name(node.type)
            if type_name in local_types:
                for declarator in node.declarators:
                    var_types[declarator.name] = local_types[type_name]

        # Also catch `new Foo(...)` invocations as method-on-Foo's-constructor reference.
        for _, node in tree.filter(javalang.tree.ClassCreator):
            short = _type_name(node.type)
            if short in local_types:
                fqcn = local_types[short]
                arity = len(node.arguments or [])
                classes[fqcn]["methods"].append({
                    "signature": f"<init>/{arity}",
                    "kind": "constructor",
                    "cobol_provenance": {"lines": ""},
                })

        # Capture every method invocation whose qualifier resolves to a tracked var.
        for _, node in tree.filter(javalang.tree.MethodInvocation):
            qualifier = node.qualifier or ""
            method = node.member
            if qualifier in var_types:
                fqcn = var_types[qualifier]
                arity = len(node.arguments or [])
                classes[fqcn]["methods"].append({
                    "signature": f"{method}/{arity}",
                    "cobol_provenance": {"lines": ""},
                })

    # Deduplicate methods (same signature emitted twice from two test files).
    for cls in classes.values():
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for m in cls["methods"]:
            sig = m["signature"]
            if sig in seen:
                continue
            seen.add(sig)
            deduped.append(m)
        deduped.sort(key=lambda m: m["signature"])
        cls["methods"] = deduped

    # Mark ports by package-segment heuristic.
    ports: list[dict[str, Any]] = []
    for fqcn, cls in classes.items():
        if ".domain.port." in fqcn or fqcn.endswith("Port"):
            cls["kind"] = "domain-port"
            ports.append({
                "fqcn": fqcn,
                "external_boundary": _infer_boundary_from_fqcn(fqcn),
                "justification": "crosses-external-boundary",
                "methods": cls["methods"],
            })
        else:
            cls["kind"] = _infer_kind_from_fqcn(fqcn)

    class_list = sorted(classes.values(), key=lambda c: c["fqcn"])
    ports.sort(key=lambda p: p["fqcn"])

    return {
        "slice": slice_name,
        "generated_by": "test-author-extracted",
        "generation_run_id": run_id,
        "source_anchor": _build_source_anchor(
            cobol_source, copybooks, jcl, fixture, expected_output
        ),
        "classes": class_list,
        "ports": ports,
        "archunit_assertions": [],
    }


# ---- code-author class extraction -------------------------------------------

# Map package segments -> kind. First match wins.
KIND_BY_SEGMENT = [
    (".domain.model.",     "domain-model"),
    (".domain.port.",      "domain-port"),
    (".application.usecase.", "application-usecase"),
    (".adapter.in.",       "adapter-in"),
    (".adapter.out.",      "adapter-out"),
    (".infra.config.",     "infra-config"),
    (".infra.observability.", "infra-observability"),
]

_PROVENANCE_RE = re.compile(r"//\s*from\s+COBOL\s+lines\s+(\d+\s*-\s*\d+)", re.IGNORECASE)


def _build_class_dict(
    jpath: Path, package: str, type_decl: Any
) -> dict[str, Any] | None:
    name = getattr(type_decl, "name", None)
    if not name or not _is_public(type_decl):
        return None
    fqcn = f"{package}.{name}" if package else name
    kind = _infer_kind_from_fqcn(fqcn)

    methods: list[dict[str, Any]] = []
    text_lines = jpath.read_text(errors="replace").splitlines()
    is_interface = _is_interface(type_decl)
    for member in getattr(type_decl, "body", []) or []:
        if not isinstance(member, javalang.tree.MethodDeclaration):
            continue
        if not _is_public_member(member, owner_is_interface=is_interface):
            continue
        sig = _format_method_signature(member)
        prov = _extract_provenance_for(member, text_lines)
        methods.append({
            "signature": sig,
            "cobol_provenance": {"lines": prov},
        })

    methods.sort(key=lambda m: m["signature"])

    return {
        "fqcn": fqcn,
        "kind": kind,
        "methods": methods,
    }


def _build_port_dict(cls_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "fqcn": cls_dict["fqcn"],
        "external_boundary": _infer_boundary_from_fqcn(cls_dict["fqcn"]),
        "justification": "crosses-external-boundary",
        "methods": cls_dict["methods"],
    }


def _is_public(type_decl: Any) -> bool:
    mods = set(getattr(type_decl, "modifiers", []) or [])
    return "public" in mods or len(mods) == 0  # package-private classes are still public-API for our purposes


def _is_interface(type_decl: Any) -> bool:
    return isinstance(type_decl, javalang.tree.InterfaceDeclaration)


def _is_public_member(member: Any, *, owner_is_interface: bool = False) -> bool:
    """A method is public if it carries `public`, OR if it's defined on an interface
    (interface members are implicitly public unless explicitly private/protected).
    """
    mods = set(getattr(member, "modifiers", []) or [])
    if "public" in mods:
        return True
    if owner_is_interface and not (mods & {"private", "protected"}):
        return True
    return False


def _format_method_signature(method: Any) -> str:
    """Produce a canonical, JLS-ordered method signature string."""
    jls_order = ("public", "protected", "private",
                 "static", "final", "abstract", "default", "synchronized", "native", "strictfp")
    mods = list(getattr(method, "modifiers", []) or [])
    mods_sorted = [m for m in jls_order if m in mods]
    return_type = _type_name(method.return_type) if method.return_type else "void"
    params = ", ".join(
        f"{_type_name(p.type)} {p.name}" for p in (method.parameters or [])
    )
    parts = mods_sorted + [return_type, f"{method.name}({params})"]
    return " ".join(parts)


def _type_name(t: Any) -> str:
    if t is None:
        return "void"
    name = getattr(t, "name", None) or ""
    args = getattr(t, "arguments", None)
    if args:
        args_str = ", ".join(_type_name(a.type) for a in args if a.type)
        if args_str:
            name = f"{name}<{args_str}>"
    if getattr(t, "dimensions", None):
        name = name + "[]" * len(t.dimensions)
    return name


def _extract_provenance_for(method: Any, source_lines: list[str]) -> str:
    """Look for `// from COBOL lines N-M` comment immediately above the method."""
    pos = getattr(method, "position", None)
    if pos is None:
        return ""
    line_no = pos.line  # 1-based
    # Scan up to 6 lines above for a provenance comment.
    for offset in range(1, 7):
        idx = line_no - 1 - offset
        if idx < 0 or idx >= len(source_lines):
            break
        m = _PROVENANCE_RE.search(source_lines[idx])
        if m:
            return m.group(1).replace(" ", "")
    return ""


def _infer_kind_from_fqcn(fqcn: str) -> str:
    dotted = "." + fqcn + "."
    for seg, kind in KIND_BY_SEGMENT:
        if seg in dotted:
            return kind
    return "other"


def _infer_boundary_from_fqcn(fqcn: str) -> str:
    if "console" in fqcn.lower() or "output" in fqcn.lower():
        return "console:stdout"
    if "file" in fqcn.lower():
        return "file:fixed-width"
    if "db" in fqcn.lower() or "sql" in fqcn.lower() or "repository" in fqcn.lower():
        return "db:relational"
    return "unknown"


def _empty_class_record(fqcn: str) -> dict[str, Any]:
    return {"fqcn": fqcn, "kind": "unknown", "methods": []}


# ---- source-anchor ----------------------------------------------------------

def _sha256_of(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_source_anchor(
    cobol_source: Path | None,
    copybooks: list[Path] | None,
    jcl: list[Path] | None,
    fixture: Path | None,
    expected_output: Path | None,
) -> dict[str, Any]:
    """Compute the source_anchor block — every SHA the harness can compute."""
    out: dict[str, Any] = {
        "cobol_path": str(cobol_source) if cobol_source else "",
        "cobol_sha256": _sha256_of(cobol_source),
        "copybooks": [
            {"name": str(c), "sha256": _sha256_of(c)}
            for c in (copybooks or [])
        ],
        "jcl": [
            {"path": str(j), "sha256": _sha256_of(j)}
            for j in (jcl or [])
        ],
        "dcl": [],
        "ddl": [],
    }
    if fixture is not None:
        out["fixture"] = {"path": str(fixture), "sha256": _sha256_of(fixture)}
    if expected_output is not None:
        out["expected_output"] = {"path": str(expected_output), "sha256": _sha256_of(expected_output)}
    return out


# ---- file walking -----------------------------------------------------------

def _iter_java_files(root: Path, *, skip_tests: bool = False, only_tests: bool = False):
    if not root.exists():
        return
    for p in root.rglob("*.java"):
        is_test = "test" in p.parts
        if skip_tests and is_test:
            continue
        if only_tests and not is_test:
            continue
        yield p
