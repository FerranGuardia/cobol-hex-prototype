"""Cache + drift detection. The four-layer determinism story lives here."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

CACHE_SCHEMA_VERSION = "v1"


def cache_key(*, prompt: str, context: str, model: str, seed: int) -> str:
    """Stable hash of everything that should affect output.

    If two callers pass identical (prompt, context, model, seed), they share a cache key.
    Bumping CACHE_SCHEMA_VERSION invalidates all caches; do that intentionally on breaking changes.
    """
    h = hashlib.sha256()
    for piece in (CACHE_SCHEMA_VERSION, model, str(seed), prompt, context):
        h.update(piece.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


@dataclass
class CacheStore:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict[str, Any] | None:
        p = self.root / f"{key}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def put(self, key: str, value: dict[str, Any]) -> None:
        p = self.root / f"{key}.json"
        p.write_text(json.dumps(value, indent=2, sort_keys=True))

    def run_or_load(
        self,
        key: str,
        fn: Callable[[], dict[str, Any]],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        if not force:
            cached = self.get(key)
            if cached is not None:
                return cached
        value = fn()
        self.put(key, value)
        return value


def diff_byte(a: str, b: str) -> bool:
    """True if byte-identical."""
    return a == b


def diff_ast_java(a: str, b: str) -> bool:
    """True if Java AST-equivalent.

    Tries `javalang`. If parsing fails, falls back to a normalized-whitespace compare
    (so we never crash the validator on malformed output).
    """
    try:
        import javalang  # type: ignore
    except ImportError:
        return _normalized_eq(a, b)

    try:
        tree_a = javalang.parse.parse(a)
        tree_b = javalang.parse.parse(b)
    except (javalang.parser.JavaSyntaxError, javalang.tokenizer.LexerError):
        return _normalized_eq(a, b)

    return _ast_dump(tree_a) == _ast_dump(tree_b)


def _ast_dump(tree: Any) -> str:
    """Stringify a javalang tree, ignoring position info that may legitimately vary."""
    parts: list[str] = []
    for path, node in tree:  # type: ignore[union-attr]
        parts.append(type(node).__name__)
        for attr in sorted(getattr(node, "attrs", ())):
            val = getattr(node, attr, None)
            if attr in {"position", "_position"}:
                continue
            parts.append(f"{attr}={val!r}")
    return "|".join(parts)


def _normalized_eq(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())
