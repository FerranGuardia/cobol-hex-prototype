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
