# cobol-hex-prototype

> Working name. Rename at mentor handoff.

A research prototype: convert legacy COBOL into a modern hexagonal-architecture Java service with OpenTelemetry instrumentation, using Codex as the LLM backend. Driven by an Iria-style multi-phase deterministic pipeline (after `newABINA`).

**Status:** infrastructure built; pipeline not yet calibrated. We are at Phase 1b → 5 (see [`docs/INFRA.md`](docs/INFRA.md) and the project diary).

---

## Quick start (any Mac / Linux machine)

```bash
# 1. Clone
git clone https://github.com/<owner>/cobol-hex-prototype.git
cd cobol-hex-prototype

# 2. Python environment (3.11+ required)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Point at a COBOL corpus
#    Default: assumes CardDemo cloned as sibling directory
ln -s ../CardDemo corpus/CardDemo
#    Or set COBOL_CORPUS env var to any path
export COBOL_CORPUS="$(pwd)/corpus/CardDemo"

# 4. Codex CLI (subscription-based, login once)
#    https://github.com/openai/codex
brew install codex          # or: npm i -g @openai/codex
codex login                  # opens browser, log in with ChatGPT subscription

# 5. Run inventory phase on the default slice
app inventory --slice app-transaction-type-db2

# 6. Run the full pipeline on a single file
app run --file corpus/CardDemo/app/app-transaction-type-db2/cbl/COBTUPDT.cbl

# Artifacts land in artifacts/<run-id>/
ls artifacts/
```

## What the pipeline does

Eight phases, modeled after the `newABINA` Iria method:

| # | Phase | Output |
|---|---|---|
| F1 | **Inventory** | Static scan of the corpus → `artifacts/inventory.json` |
| F2 | **Capture** | Documented expected behavior (no runtime; out of scope per project doctrine) → `capture.json` |
| F3 | **Context Pack** | COBOL source + DDL + DCL + JCL + README excerpts → `context_pack.md` (no embeddings) |
| F4 | **Golden Master** | Test vectors derived from F2 + F3 → `golden_master.json` |
| F5 | **Convert** | Codex pipeline → modernized Java in `artifacts/<run-id>/output/` |
| F6 | **Validate** | Four-tier acceptance: invariants / semantic / determinism / economics |
| F7 | **Inventory update** | Mark slice as validated in `inventory.json` |
| F8 | **Evidence gate** | Final review of logs + metrics + drift |

## Acceptance tiers (the determinism contract)

| Tier | What | Target |
|---|---|---|
| T1 | Output compiles + hex shape + OTel on every adapter + type-clean | **100% (hard gate)** |
| T2 | Behaviorally equivalent to expected outputs on the golden master | **≥ 95%** |
| T3 | Run-to-run determinism (3× same input) | **≥ 80% byte-identical, ≥ 95% AST-equivalent** |
| T4 | Cost/file, time/file, human-fix rate | **Bounded; targets calibrated after Phase 5** |

See [`SPEC.md`](SPEC.md) for the perfect-path target shape and [`FAILURES.md`](FAILURES.md) for the catalog of known failure modes (the actual face of the tool — see project doctrine).

## Repository layout

```
cobol-hex-prototype/
├── README.md           # this file
├── SPEC.md             # perfect-path target spec (aspirational)
├── FAILURES.md         # catalog of known failures (the honest face)
├── docs/
│   └── INFRA.md        # architecture decisions and rationale
├── pyproject.toml
├── .env.example
├── src/app/
│   ├── cli.py          # entry point (typer)
│   ├── core/           # coordinator, codex wrapper, determinism, schemas
│   ├── pipeline/       # F1..F8 phase implementations
│   └── agents/         # agent base class
├── prompts/            # markdown personas (analyzer, converter, ...)
├── corpus/             # link or path to COBOL source corpus
├── artifacts/          # outputs per run (gitignored, except .gitkeep)
└── tests/
```

## Configuration

Copy `.env.example` to `.env` and adjust. All env vars are also overridable via CLI flags.

```bash
COBOL_CORPUS=/abs/path/to/CardDemo   # required
CODEX_BIN=codex                       # codex CLI binary
LLM_MODEL=gpt-5-codex                  # model identifier
LLM_TEMPERATURE=0                      # 0 for determinism
LLM_SEED=42                            # seed for reproducibility
CACHE_DIR=.cache                       # cache for deterministic re-runs
LOG_LEVEL=INFO
```

## Determinism strategy

LLM output is non-deterministic by default. We compensate via:

1. **`temperature=0` + `seed`** on every call.
2. **Prompt+context hashing** — every `(prompt, context, model, seed)` tuple has a stable cache key. Identical inputs return cached output unless `--force`.
3. **Drift detection** — `app validate drift --runs 3` runs the same input 3× and reports byte/AST divergence.
4. **Idempotent agents** — passing converter output back through the converter should be a no-op (round-trip check).

See [`docs/INFRA.md#determinism`](docs/INFRA.md#determinism) for details and tradeoffs.

## What is *not* in scope (and won't be)

- Running the original COBOL. We consume `(source, sample data, expected outputs)`. The "before" runtime is somebody else's problem.
- Translating arbitrary mainframe stacks. First slice is DB2-batch COBOL. CICS comes later, IMS/MQ much later.
- A web portal. The Azure repo's `McpChatWeb` is intentionally not ported.
- 100% conversion on every COBOL file. We measure failure rates honestly (see `FAILURES.md`) instead of curating away hard cases.

## License

Apache 2.0. CardDemo (consumed as input only) is © Amazon, Apache 2.0.

## Acknowledgements

- `newABINA` — the Iria 8-phase methodology this project mirrors.
- `Azure-Samples/legacy-modernization-agents` — reference for agent persona prompts.
- `aws-samples/aws-mainframe-modernization-carddemo` — input corpus.
