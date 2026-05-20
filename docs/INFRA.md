# Infrastructure decisions

Living document. Each decision below is a deliberate choice with a reason. Revise in place when reality forces it; do not delete history — append a `Superseded by …` note instead.

---

## 1. Language: Python 3.11+

**Why:** Codex CLI is shell-invoked; we need a small orchestrator that primarily moves text and JSON between files and subprocesses. Python is fastest to write, has the strongest LLM-tooling ecosystem (Pydantic, Rich, Typer), and matches `newABINA`'s host runtime so methodology lifts are cheap.

**Tradeoff:** Slower than Go/Rust at scale. Not a concern: I/O-bound + LLM-bound. CPU is not the bottleneck.

---

## 2. Package management: stdlib venv + pip + `pyproject.toml`

**Why:** Works on any Mac/Linux without extra tooling. `uv` is faster and nicer, but adds a dependency we'd have to explain in onboarding. We optimize for "clone, `pip install -e .`, run".

**Tradeoff:** Resolves slower than `uv`. Acceptable.

---

## 3. CLI framework: Typer

**Why:** Click ergonomics with type hints. Self-documents from function signatures. Zero learning cost for someone reading the code.

---

## 4. Schemas: Pydantic v2

**Why:** Every artifact crossing a phase boundary is validated JSON. Pydantic v2 is fast, gives free serialization, and `model_json_schema()` lets us emit JSON Schema docs from the same source. `newABINA` does this and we mirror it.

---

## 5. LLM invocation: subprocess to Codex CLI

**Why:** User commitment is Codex on subscription. The CLI handles auth (`codex login`), streaming, MCP tool registration, and rate-limiting for us. We don't reimplement what the CLI already does well.

**Shape:**
```python
subprocess.run(["codex", "exec", "--json", "--seed", str(seed), prompt_path], ...)
```

**Fallback:** If `LLM_BACKEND=openai-api` is set, we use the official `openai` SDK with the same prompt. Documented but not the default.

---

## 6. Determinism scaffolding

LLM output is non-deterministic. We compensate at four layers:

### 6.1 Cache key
```
sha256(prompt_text || context_text || model_id || seed || schema_version)
```
Stored at `.cache/<hex>.json`. Returns cached output unless `--force`. Implemented in `src/app/core/determinism.py`.

### 6.2 `temperature=0` + `seed` (default seed=42)
Passed to every Codex invocation. Documented as the default; overridable per call for adversarial tests.

### 6.3 Drift detection
`app validate drift --file X --runs 3` invokes the converter three times with the same key, computes:
- Byte-identical rate
- AST-equivalent rate (Java AST via `javalang`)
- Diff summary

T3 thresholds: ≥80% byte-identical, ≥95% AST-equivalent.

### 6.4 Idempotence (round-trip)
Convert → Convert again on the output → diff. If non-empty, the converter is leaking non-determinism. Round-trip test runs as part of T1.

---

## 7. Phase boundaries are files, not function calls

**Why:** newABINA's biggest engineering win is that every phase produces a file the next phase consumes. This means:
- Phases are independently runnable / re-runnable.
- Caching is trivial (file hash = cache key).
- Debugging is forensic — look at the artifact, not the stack.
- A failure in F5 doesn't require re-running F1..F4.

**Manifest:**

| Phase | Reads | Writes |
|---|---|---|
| F1 Inventory | `corpus/` | `artifacts/inventory.json` |
| F2 Capture | (out of scope; consumes pre-existing docs) | `artifacts/<run-id>/capture.json` |
| F3 Context Pack | source + capture | `artifacts/<run-id>/context_pack.md` |
| F4 Golden Master | capture + spec | `artifacts/<run-id>/golden_master.json` |
| F5 Convert | context_pack + persona prompts | `artifacts/<run-id>/output/**/*.java` |
| F6 Validate | output + golden_master | `artifacts/<run-id>/validation.json` |

---

## 8. No vector embeddings, no RAG

**Why:** newABINA proved >15% semantic drift on legacy code. Context packs are deterministic markdown injected into the prompt directly.

**Tradeoff:** Context size grows with codebase. Mitigated by chunking (per the Azure repo's smart-chunking architecture, ported to our coordinator in later phases).

---

## 9. Artifact directory layout (per run)

```
artifacts/
├── inventory.json              # one global, latest scan
└── <run-id>/                    # one per `app run` invocation
    ├── manifest.json            # all CLI args, env vars, git SHA, timestamps
    ├── capture.json             # F2
    ├── context_pack.md          # F3
    ├── golden_master.json       # F4
    ├── output/                  # F5 generated Java
    │   └── com/.../*.java
    ├── validation.json          # F6
    ├── logs/                    # raw codex stdout/stderr per call
    └── traces/                  # codex tool-call traces if enabled
```

Run ID format: `YYYYMMDD-HHMMSS-<short-sha-of-input>`.

---

## 10. Acceptance matrix as a versioned artifact

`acceptance/matrix.json` records, per converted file:

```json
{
  "file": "COBTUPDT.cbl",
  "run_id": "20260520-184700-abc123",
  "T1": {"status": "pass", "details": {...}},
  "T2": {"status": "fail", "score": 0.87, "diffs": [...]},
  "T3": {"status": "pass", "byte_identical_rate": 0.93, "ast_equivalent_rate": 1.0},
  "T4": {"cost_usd": 0.42, "wall_seconds": 78, "human_fixes": 0},
  "failure_tags": ["T2-BEHAVIOR-MISMATCH"]
}
```

Updated by F6. Never edited manually. Source of truth for "is the pipeline industrialization-ready" (defined as: every tier green across 3 consecutive distinct slices).

---

## 11. Failure mode catalog

`FAILURES.md` is the canonical list of failure tags. Adding a tag without code support is invalid; the validator emits only tags from this file. Reviewed at each industrialization gate.

---

## 12. Prompts as data

Prompts live in `prompts/<agent>.md`. They are NOT embedded in Python source. Reason: agents are tuned by editing Markdown, no code change. Mirrors Azure repo's pattern.

Initial set:
- `prompts/analyzer.md` — extracts structure from COBOL
- `prompts/converter.md` — emits hex+OTel Java
- `prompts/validator.md` — checks generated output against context pack invariants

More agents added as we discover decompositions during iteration.

---

## 13. What is not in this repo

- The COBOL corpus (cloned separately; symlinked or env-pointed)
- Codex CLI itself (installed system-wide; version pinned in README)
- AI model weights (cloud-side)
- The Azure reference repo and newABINA (sibling research repos)

---

## 14. Out-of-scope decisions (revisit later)

- **Web portal** (Azure repo's `McpChatWeb`). Useful for demos; nothing on the critical path.
- **Multi-model ensembling.** Only Codex for now.
- **Real-time pipeline visualization.** Logs + JSON artifacts are sufficient until they aren't.
- **Hosted CI.** Local-first until the slice count justifies it.

---

## Change log

| Date | Change | Reason |
|---|---|---|
| 2026-05-20 | Initial infrastructure created | Phase 1a |
