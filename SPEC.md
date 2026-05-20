# SPEC — the perfect-path output

This document describes what the *ideal* output of the pipeline should look like for any given COBOL input. It is aspirational. Real output will rarely match this exactly; the gap is measured by validation tiers T1–T4 and tracked per file in `acceptance/matrix.json`.

> This document is one of two parallel sources of truth. The other is [`FAILURES.md`](FAILURES.md). When they disagree, the FAILURES catalog wins — reality beats aspiration.

---

## Output target shape (per converted COBOL program)

A single COBOL program (e.g., `COBTUPDT.cbl`) should produce a self-contained Java module shaped like this:

```
output/
└── com/example/cobol/<program-name-kebab>/
    ├── domain/
    │   ├── model/              # value objects, entities; no framework imports
    │   └── port/               # interfaces; one file per port
    ├── application/
    │   └── usecase/            # use-case classes; orchestrate domain via ports
    ├── adapter/
    │   ├── in/                 # driving adapters (CLI, REST, batch driver)
    │   └── out/                # driven adapters (DB, file, queue)
    └── infra/
        ├── config/             # wiring (DI), no logic
        └── observability/      # OTel SDK bootstrap (shared)
```

## Hard invariants (T1 — every output must satisfy these)

These are non-negotiable. The validator fails the run if any of these are violated.

| # | Invariant | Enforced by |
|---|---|---|
| 1 | Output compiles with the project's Maven/Gradle build | `mvn compile` exit 0 |
| 2 | `domain/` has zero framework imports (no `org.springframework`, no `jakarta.persistence`, no `io.opentelemetry`, etc.) | ArchUnit `noClasses().that().resideInAPackage("..domain..").should().dependOnClassesThat()...` |
| 3 | `domain/` does not depend on `application/`, `adapter/`, or `infra/` | ArchUnit |
| 4 | `application/usecase/` depends only on `domain/` | ArchUnit |
| 5 | `adapter/in/` and `adapter/out/` depend only on `application/` and `domain/` | ArchUnit |
| 6 | Every port has at least one adapter implementation | ArchUnit `interfaces().that().resideInAPackage("..port..").should().beImplemented()` |
| 7 | Every public method on a use case opens an OTel span | Annotation-driven + AST scan |
| 8 | Every adapter method that crosses an external boundary opens a span and records the operation type as an attribute | AST scan |
| 9 | No generated `// TODO`, `// FIXME`, or stub return statements (`throw new UnsupportedOperationException`) | Lexical scan |
| 10 | No COBOL idioms leaked: no GOTO, no global state, no `Object`-typed catch-all parameters | Lexical scan |
| 11 | All Java files pass `google-java-format -i --dry-run` | Formatter exit 0 |
| 12 | Round-trip stable: convert output through validator-agent → output unchanged | Hash diff |
| 13 | File-organization semantics preserved: COBOL `ORGANIZATION IS INDEXED`/`SEQUENTIAL`/`RELATIVE` with fixed records → Java adapter reads fixed-length byte blocks (not newline-delimited text) | Mechanical scan: COBOL `SELECT ... ORGANIZATION IS X` vs Java adapter's read primitive (`readNBytes` vs `readLine`) |
| 14 | COBOL abends terminate the process: `CALL 'CEE3xxx'` → Java `System.exit(...)` or a custom `Error` subclass, never a catchable `RuntimeException` | Mechanical scan: COBOL `CALL 'CEE3...'` and matching Java path |
| 15 | No filesystem types (`Path`, `File`, `URI`) appear in `domain/` or `application/` class signatures | AST scan on import + signature lists |
| 16 | When the Java manipulates byte values for display formatting, an explicit `// charset:` comment justifies the encoding assumption (ASCII or EBCDIC) | Lexical scan: presence of byte→int conversion + nearby `// charset:` comment |

## Soft conventions (T1 — strong defaults, not hard fails)

- Package name: `com.example.cobol.<source-program-name-kebab-case>`
- All identifiers are renamed from COBOL `LIKE-THIS` to Java `likeThis` / `LikeThis`
- A COBOL data record maps to a Java record (Java 17+ feature) by default
- DB2 cursor patterns map to `try-with-resources` over a `Stream<Row>`
- SQL stays as parameterized native SQL via a `RowMapper`-like adapter; no JPA entities unless the use case demands it
- `EXEC SQL` blocks become methods on the relevant out-port (one method per SQL operation)
- Batch entry point: `public final class BatchRunner { public static void main(...) }` in `adapter/in/batch/`

## OpenTelemetry shape

- Single OTel SDK bootstrap in `infra/observability/OpenTelemetryConfig.java`
- Auto-instrumentation via the OpenTelemetry Java agent at runtime; manual instrumentation only where the agent can't see
- Span naming: `<package>.<usecase>.<operation>` or `<package>.<adapter>.<external-op>`
- Required span attributes:
  - `cobol.source.program` — original program name
  - `cobol.source.line.range` — line range of the originating COBOL (provenance)
  - `db.statement` — for SQL adapters (already standard OTel semantic conv)
  - `messaging.system` — for MQ adapters (standard)
- Trace context propagated end-to-end on the W3C `traceparent` header

## Hex pragmatism rule (the anti-over-abstraction guardrail)

A port is justified only if at least one of the following holds:
1. It crosses an external boundary (DB, file, queue, network).
2. There are ≥2 adapter implementations *in use*.
3. The COBOL source has explicit configuration switching between behaviors (e.g., FILE STATUS branching).

Adding a port that satisfies none of these is a `T1-OVER-ABSTRACTION` failure tag. Single-implementer interfaces inside the application layer are forbidden unless they're explicit ports.

## Provenance

Every generated Java file MUST start with a comment block:

```java
/*
 * Generated from: app/app-transaction-type-db2/cbl/COBTUPDT.cbl, lines 80-237.
 * Run ID: 20260520-184700-abc123.
 * Persona: prompts/converter.md @ <git sha>.
 * Determinism: temp=0, seed=42, cache-key=<sha>.
 *
 * Do not edit manually. Re-run the pipeline to regenerate.
 */
```

This is non-negotiable. Without provenance the output is not auditable, and auditability is the whole point.

---

## Public Contract — the narrow channel between personas

The pipeline runs two LLM personas in parallel and **independently** on each slice: [`code-author`](prompts/code-author.md) (produces Java + a contract) and [`test-author`](prompts/test-author.md) (produces tests + a contract). Each emits a JSON document conforming to [`schemas/public-contract.schema.json`](schemas/public-contract.schema.json). The harness diffs the two; disagreement is the signal that the COBOL source admits two interpretations of its public behavior, and triggers the [Investigator](prompts/investigator/README.md).

### Why two-pass blind generation

A single LLM call that writes both the code and the tests can trivially make the tests pass against its own code (tautology). Forcing two blind generators to converge on a contract derived from the COBOL source independently is the strongest determinism signal available within a single model. The principle: **do less when the pipeline holds more**. See the project's `feedback-cost-vs-rework` memory.

### What's in the contract

The Contract object captures *only the publicly observable shape* of the Java module:

- **classes** — FQCN, kind (`domain-model | domain-port | usecase | adapter-in | adapter-out | infra-config | infra-observability`), constructor, public methods.
- **methods** — canonical Java signature, COBOL provenance (file + line range + paragraph), declared exceptions, OTel spans emitted, ordered side-effects, fixture-grounded postconditions, exception conditions.
- **ports** — FQCN, methods, external boundary kind, justification (which of the three hex pragmatism rules applies).
- **source_anchor** — SHA-256 of every source artifact that influenced the contract. Any drift in COBOL / copybook / fixture invalidates the cached contract.
- **archunit_assertions** — generated ArchUnit DSL expressions for the SPEC invariants.

What's NOT in the contract: implementation bodies, private fields, internal helper methods, package-private utilities. Only the public surface that an external test could observe.

### Canonical form (required for K-vote and contract-diff)

Both personas must emit contracts in canonical form so byte-level field comparison is meaningful:

- All arrays sorted: `classes` by `fqcn`, `methods` by `signature`, `side_effects` by `ordering`, `throws` lexicographically, `archunit_assertions` by `rule`.
- All Java signatures normalized: single space between tokens; modifiers in JLS order (`public protected private` then `static final abstract`); return type before name; generic params right-bound (`List<String>`, not `List <String>`).
- All paths Unix-separator (`/`), relative to the repo root unless `source_anchor` specifies otherwise.
- All SHA-256 lowercase hex.
- Provenance line ranges as `start-end` with no spaces.

The harness's `harness/contract/validate.py` rejects non-canonical contracts; the persona is re-prompted with the canonicalization error until it produces valid output or hits the retry budget (default 3).

## Test-Meaningfulness Ladder

Every generated JUnit test carries exactly one of four `@Tag` annotations, ranked by how grounded its assertions are in source-of-truth external to the LLM:

| Tag | Grounded in | Tautology risk | Counts toward T2-green? |
|---|---|---|---|
| `T2-parsing` | COPYBOOK byte layout — fixed-width fields, REDEFINES, OCCURS. External fact. | None | Yes |
| `T2-fixture` | `carddata.txt` rows mapped to expected parsed-field values. External fact. | None | Yes |
| `T2-consistency` | The contract itself — proves *code matches contract*, not *contract matches COBOL*. | **High by design.** Tautological. | **Partial credit only.** |
| `T2-equivalence` | Hand-curated `expected-output.txt` (or the `abhi-ksh/aws-carddemo-modernized` oracle, or mechanically extracted assertions). | None — the only true equivalence test. | **Load-bearing.** Required for T2-green. |

A slice is **T2-green only when at least one `T2-equivalence` test exists and passes**. `T2-consistency` alone does not advance the slice — that is the explicit guard against the "tests passed but the wiring was wrong, and the source had the truth" failure mode.

## Determinism Stack

The pipeline applies a stack of determinism techniques from the LLM-systems literature. Listed in the order they execute on a slice. Each is non-optional unless flagged DEFERRED.

| # | Technique | Where | Status | Notes |
|---|---|---|---|---|
| 1 | **Temperature=0** at the model API | `core/codex.py` | In place | Standard greedy decoding |
| 2 | **Prompt + context + model + seed cache key** | `core/determinism.py` | In place | Standard memoization |
| 3 | **Schema-enforced contract decoding** via validate-and-retry | `harness/contract/validate.py` | Phase A | Contract must pass [`schemas/public-contract.schema.json`](schemas/public-contract.schema.json); on failure, re-prompt with validator error |
| 4 | **K-vote self-consistency on the contract** | `harness/contract/kvote.py` | Phase A | Wang et al. 2022. K=5 default; field-by-field majority |
| 5 | **Two-pass blind generation** (code-author ‖ test-author) | `src/app/pipeline/convert.py` (rewrite Phase A) | Phase A | Independent generators on the same source; contract-diff is the signal |
| 6 | **Mechanical fact extraction** (COBOL EXEC SQL, FILE STATUS, PARAGRAPH, COPY) | `harness/extract/cobol_facts.py` | Phase A | Non-LLM assertions derived directly from source |
| 7 | **Idempotence check** (code-author on its own output is a no-op) | `harness/checks/idempotence.py` | Phase B | Fixed-point convergence |
| 8 | **Reverse-translation oracle** (Java→COBOL, structural diff) | `harness/checks/reverse_translate.py` + [`prompts/reverse-translator.md`](prompts/reverse-translator.md) | Phase B | NMT back-translation technique |
| 9 | **Hermetic containerized execution** (pinned JDK, Maven, ArchUnit, formatter, ProLeap) | `Dockerfile` + `Makefile` | Phase B | Reproducible builds |
| 10 | **COBOL-AST-as-input** (ProLeap → typed AST → all personas) | `src/app/pipeline/cobol_ast.py` + persona-input changes | Phase C | Structural input is far more deterministic than raw text |
| 11 | **Bytecode-level T3 diff** | — | DEFERRED | See [docs/FUTURE-IMPROVEMENTS.md](docs/FUTURE-IMPROVEMENTS.md) §D4 |
| 12 | **Cross-model differential** (Codex + Claude + Gemini) | — | DEFERRED — user stack | See [docs/FUTURE-IMPROVEMENTS.md](docs/FUTURE-IMPROVEMENTS.md) §D1 |

The maximalism principle drives this list: every applicable technique that is not stack-incompatible is in scope. Cost is not the budget constraint; downstream debugging is.

---

## What is NOT in the spec (deliberate omissions)

- **No reactive streams.** Block-on-IO is fine for batch and admin paths. Reactive is a future decision.
- **No Spring Boot lock-in in `domain/` or `application/`.** They run with plain JDK and JUnit. `adapter/` and `infra/` may use Spring.
- **No GraalVM native image requirement.** Future option, not a current goal.
- **No web frontend.** newABINA pairs Java backend with React; this prototype is backend-only until that becomes worth doing.

---

## How this spec is used

The spec drives:

1. The `converter.md` persona's system prompt (this file is partially injected).
2. The validator's invariant checks (T1).
3. The score for "ideal alignment" in T2 reports.
4. Reviews when a slice fails — we trace failures back to which part of the spec wasn't met.

When iteration reveals the spec is wrong (e.g., a guardrail makes generation impossible), the spec is amended via PR with rationale. Do not silently bend the spec to match reality — that defeats the purpose of having one.
