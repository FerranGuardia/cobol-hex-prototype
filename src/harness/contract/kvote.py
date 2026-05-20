"""K-vote field-by-field majority across N contracts (Determinism Stack #4).

Run the same persona K=5 times (independent invocations with the same input)
and take field-by-field majority on each leaf path. The K-vote majority
contract is the artifact downstream consumers use; per-field agreement rate
is emitted in `kvote_metadata.field_agreement`.

Agreement threshold default: 0.6 (3 of 5 = 0.6). Fields below threshold are
flagged as `T3-KVOTE-DIVERGENCE` — the persona is non-deterministic on that
field, which is a real signal to surface.

Reference: Wang et al. 2022, "Self-Consistency Improves Chain of Thought
Reasoning in Language Models".

Pure module: no Codex orchestration. The K=N invocations happen upstream
(orchestrator passes us the N parsed contracts).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

DEFAULT_AGREEMENT_THRESHOLD = 0.6


@dataclass
class KVoteResult:
    majority: dict[str, Any]
    field_agreement: dict[str, float]
    divergent_fields: list[str] = field(default_factory=list)
    k: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "majority": self.majority,
            "field_agreement": self.field_agreement,
            "divergent_fields": self.divergent_fields,
            "k": self.k,
        }


def kvote(
    contracts: list[dict[str, Any]],
    *,
    threshold: float = DEFAULT_AGREEMENT_THRESHOLD,
    run_ids: list[str] | None = None,
) -> KVoteResult:
    """Compute field-by-field majority across `contracts`.

    Flatten each contract to {path -> canonical-string-value}, collect across K,
    take the most-common value per path, and reconstruct a majority dict.
    """
    if len(contracts) < 3:
        raise ValueError(f"K-vote requires K >= 3; got {len(contracts)}")

    flat_per_run = [_flatten(c) for c in contracts]
    all_paths: set[str] = set()
    for f in flat_per_run:
        all_paths.update(f)

    majority_flat: dict[str, str] = {}
    field_agreement: dict[str, float] = {}
    divergent: list[str] = []

    for path in sorted(all_paths):
        values = [f.get(path) for f in flat_per_run]
        present_values = [v for v in values if v is not None]
        if not present_values:
            continue
        counts: dict[str, int] = {}
        for v in present_values:
            counts[v] = counts.get(v, 0) + 1
        top_val, top_count = max(counts.items(), key=lambda kv: kv[1])
        agreement = top_count / len(contracts)
        field_agreement[path] = round(agreement, 3)
        if agreement >= threshold:
            majority_flat[path] = top_val
        else:
            # Below threshold — record as divergent; keep the most-common value
            # in the majority but flag it so downstream knows it's weak.
            majority_flat[path] = top_val
            divergent.append(path)

    majority = _unflatten(majority_flat)
    majority["generated_by"] = "kvote-majority"
    majority["kvote_metadata"] = {
        "k": len(contracts),
        "input_run_ids": run_ids or [c.get("generation_run_id", f"run-{i}") for i, c in enumerate(contracts)],
        "field_agreement": field_agreement,
    }
    return KVoteResult(
        majority=majority,
        field_agreement=field_agreement,
        divergent_fields=divergent,
        k=len(contracts),
    )


def _flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    """Path -> canonical-serialized value, for dict/list/scalar.

    Arrays of objects with an `identity` field (fqcn, signature, rule) are
    indexed by that field; other arrays by zero-based index. Leaves are
    canonicalized via `json.dumps(..., sort_keys=True)`.
    """
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_prefix = f"{prefix}.{k}" if prefix else k
            out.update(_flatten(v, new_prefix))
    elif isinstance(obj, list):
        key_field = _identity_field(prefix)
        for idx, item in enumerate(obj):
            if isinstance(item, dict) and key_field and key_field in item:
                idx_key = item[key_field]
            else:
                idx_key = str(idx)
            new_prefix = f"{prefix}[{idx_key}]"
            out.update(_flatten(item, new_prefix))
    else:
        out[prefix] = json.dumps(obj, sort_keys=True)
    return out


def _unflatten(flat: dict[str, str]) -> dict[str, Any]:
    """Inverse of _flatten. Reconstruct dict-of-dicts/lists from flat path map."""
    root: dict[str, Any] = {}
    for path, value_json in flat.items():
        value = json.loads(value_json)
        _insert(root, path, value)
    # Convert dict-with-numeric-keys back to lists
    _normalize_arrays(root)
    return root


def _insert(root: dict[str, Any], path: str, value: Any) -> None:
    parts = _split_path(path)
    cur: Any = root
    for i, (key, is_array_index) in enumerate(parts):
        is_last = i == len(parts) - 1
        if is_array_index:
            if not isinstance(cur, dict) or key not in cur:
                # Array stored as dict keyed by identity for unflatten phase
                cur[key] = {} if is_array_index else []
            if is_last:
                cur[key] = value
            else:
                next_key, next_is_array = parts[i + 1]
                if not isinstance(cur.get(key), (dict, list)):
                    cur[key] = {} if next_is_array else {}
                cur = cur[key]
        else:
            if is_last:
                cur[key] = value
            else:
                if key not in cur:
                    cur[key] = {}
                cur = cur[key]


def _split_path(path: str) -> list[tuple[str, bool]]:
    """Split `a.b[x].c[0]` into [(a,False),(b,False),(x,True),(c,False),(0,True)]."""
    parts: list[tuple[str, bool]] = []
    token = ""
    i = 0
    while i < len(path):
        c = path[i]
        if c == ".":
            if token:
                parts.append((token, False))
                token = ""
            i += 1
        elif c == "[":
            if token:
                parts.append((token, False))
                token = ""
            j = path.index("]", i + 1)
            parts.append((path[i + 1 : j], True))
            i = j + 1
        else:
            token += c
            i += 1
    if token:
        parts.append((token, False))
    return parts


def _identity_field(prefix: str) -> str | None:
    """Which field identifies array elements at this prefix (e.g. classes -> fqcn)."""
    if prefix.endswith(".classes") or prefix == "classes":
        return "fqcn"
    if prefix.endswith(".ports") or prefix == "ports":
        return "fqcn"
    if prefix.endswith(".methods"):
        return "signature"
    if prefix.endswith(".archunit_assertions") or prefix == "archunit_assertions":
        return "rule"
    return None


def _normalize_arrays(node: Any) -> None:
    """Convert dicts keyed by identity-field back into sorted lists."""
    if isinstance(node, dict):
        for key, val in list(node.items()):
            if key in ("classes", "ports", "archunit_assertions", "methods") and isinstance(val, dict):
                # Convert identity-keyed dict to list, sorted by identity
                items = list(val.values())
                node[key] = items
                for item in items:
                    _normalize_arrays(item)
            else:
                _normalize_arrays(val)
    elif isinstance(node, list):
        for item in node:
            _normalize_arrays(item)
