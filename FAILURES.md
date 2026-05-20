# FAILURES — the catalog of known failure modes

The honest face of the tool. Every documented failure tag lives here. A small, well-categorized catalog is the credibility proof; a hidden or curated-away failure is dishonesty.

> Companion to [`SPEC.md`](SPEC.md). When the spec and this catalog disagree about whether something is acceptable, this file wins. Reality beats aspiration.

---

## Status

Empty. No real runs have been executed yet. Tags below are the *scaffold* — modes we anticipate. Real tags get marked `OBSERVED` once we see them in the wild, with example artifacts.

## Catalog (scaffold)

| Tag | Tier | Trigger | Recovery | Observed |
|---|---|---|---|---|
| `T1-SCHEMA-INVALID` | T1 | Persona-emitted contract.json does not validate against `schemas/public-contract.schema.json` | Re-prompt with `jsonschema` validation error; max 3 retries | Not yet |
| `T1-COMPILE-ERROR` | T1 | Generated Java does not compile | Re-prompt with `javac` error in context; max 2 retries | Not yet |
| `T1-HEX-VIOLATION` | T1 | ArchUnit detects layer dependency violation | Re-prompt with violation list; max 2 retries | Not yet |
| `T1-OTEL-MISSING` | T1 | A use-case or adapter method lacks span instrumentation | Post-pass agent inserts spans | Not yet |
| `T1-OVER-ABSTRACTION` | T1 | A single-implementer port introduced inside `application/` layer | Re-prompt with the pragmatism rule (see SPEC.md) | Not yet |
| `T1-FORMAT-DIRTY` | T1 | `google-java-format` reports diffs | Auto-fix via formatter; pass | Not yet |
| `T1-COBOL-IDIOM-LEAK` | T1 | GOTO, global state, or COBOL-style flag-driven control flow detected | Re-prompt with idiom-list | Not yet |
| `T1-NO-PROVENANCE` | T1 | Missing or malformed provenance header on a generated file | Auto-insert; warn | Not yet |
| `T1-PATH-LEAK` | T1 | `java.nio.file.Path`, `java.io.File`, or `java.net.URI` appears in a `domain/` or `application/` class signature (constructor, method param, return type, field type) | Re-prompt with the hex purity rule + the offending signature; max 2 retries | **OBSERVED — wave-2 (CBACT02C):** `ReadCardFileUseCase.execute(Path)` leaks `Path` into the application layer |
| `T1-IDIOM-DRIFT` | T1 | A pure-value class is emitted as `final class` with explicit constructor + accessors when Java `record` syntax would have sufficed | Re-prompt with the prefer-`record` rule; soft fail (warning, not blocking) | **OBSERVED — wave-2 (CBACT02C):** `CardRecord` emitted as verbose `final class` (~30 LOC overhead vs `record`); wave-1 used `record` syntax |
| `T2-FILE-ORG-DRIFT` | T2 | COBOL declares `ORGANIZATION IS INDEXED`/`SEQUENTIAL`/`RELATIVE` with a fixed RECORD KEY but the Java adapter reads newline-delimited text (`BufferedReader.readLine()`) instead of fixed-length byte blocks (`readNBytes`) | Re-prompt with the COBOL `SELECT` statement + the file-organization rule; max 2 retries | **OBSERVED — wave-2 (CBACT02C):** `FixedWidthCardFileAdapter.readNext` uses `BufferedReader.readLine()` despite COBOL `ORGANIZATION IS INDEXED ACCESS MODE IS SEQUENTIAL RECORD KEY IS FD-CARD-NUM`. *Likelihood with iria contract present: very low — `datasets[*].organization`/`accessMode`/`recordFormat`/`recordLength`/`recordKey` are explicit. If still observed → upgrade to `T2-IRIA-CONTRACT-IGNORED`.* |
| `T2-ABEND-CATCHABLE` | T2 | COBOL `CALL 'CEE3ABD'` (or any `CEE3xxx` abend service) translates to a catchable `RuntimeException`/`IllegalStateException` instead of `System.exit(...)` or a custom `Error` subclass | Re-prompt with the COBOL line + the abend-terminal rule; max 2 retries | **OBSERVED — wave-2 (CBACT02C):** `abendProgram()` throws `IllegalStateException("CBL-ABEND-999")` instead of terminating the process. *Likelihood with iria contract present: very low — `execution.abend.semantics` says "terminal — process exits, never returns". If still observed → upgrade to `T2-IRIA-CONTRACT-IGNORED`.* |
| `T2-CHARSET-IMPLICIT` | T2 | Java code manipulates byte values for display formatting (e.g., `(int) someChar`) without an explicit `// charset:` comment justifying the encoding assumption | Re-prompt with the surrounding line and the charset-explicitness rule; soft fail (warning) | **OBSERVED — wave-2 (CBACT02C):** `FileStatusFormatter.format` does `(int) stat2` without charset comment; ASCII assumption silent. *Likelihood with iria contract present: very low — `datasets[*].encoding` + `ccsid` are explicit. If still observed → upgrade to `T2-IRIA-CONTRACT-IGNORED`.* |
| `T2-DUPLICATED-OUTPUT` | T2 | A line `DISPLAY`ed once in COBOL appears more than once in the Java's stdout because of error-handling cascade (one method writes it, then calls another that also writes it) | Re-prompt with the call chain + line-ownership rule | **OBSERVED — wave-2 (CBACT02C):** "ABENDING PROGRAM" emitted twice in close-error path (`handleIoError` then `abendProgram`) |
| `T2-IRIA-CONTRACT-IGNORED` | T2 | The Context Pack contained an authoritative `## Iria runtime contract` section but the generated Java contradicts a verbatim-take field (e.g., `datasets[*].organization`, `execution.abend.semantics`, `displayContract.*`, `fileStatusCodesBranched`). Different bug class from the original drift modes — the persona was *told* the answer and produced something else, so the failure is "didn't read / hallucinated past contract," not "guessed wrong from ambiguous COBOL." | Re-prompt with the contract field + the specific contradiction; max 2 retries. If persists 2× → Investigator (the persona may be misreading the contract section's role, or the contract itself may be wrong). | Not yet — wave-3 will be the first run with this signal wired |
| `T2-PARSING-FAIL` | T2 | A `@Tag("T2-parsing")` test fails (a COPYBOOK byte-layout assertion broke) | Re-prompt code-author with the failing field + COPYBOOK excerpt | Not yet |
| `T2-FIXTURE-FAIL` | T2 | A `@Tag("T2-fixture")` test fails (carddata.txt row does not parse as expected) | Re-prompt with the failing row + expected fields | Not yet |
| `T2-CONSISTENCY-ONLY-PASSED` | T2 | Slice has passing `T2-consistency` tests but **no** `T2-equivalence` test exists or passes. **Warning, not pass.** The wiring may be self-consistent but unverified against COBOL. | Slice is **not** T2-green. Curate `expected-output.txt` or run mechanical-extraction; do not advance until at least one `T2-equivalence` assertion holds. | Not yet |
| `T2-EQUIVALENCE-FAIL` | T2 | The `@Tag("T2-equivalence")` E2E golden-master test fails (Java's stdout differs from `expected-output.txt`) | Re-prompt with the unified diff; if persists 2× → Investigator | Not yet |
| `T2-CONTRACT-MISMATCH` | T2 | code-author and test-author contracts disagree on critical fields (class FQCNs, method signatures, ordered side-effects, ports) above the diff threshold | Investigator triages; the disagreement itself is the bug — both contracts may be wrong, one may be right, or the COBOL admits two interpretations. Do NOT advance to `mvn test`. | Not yet |
| `T2-IDEMPOTENCE-FAIL` | T2 | Re-running code-author on its own output produces ≠ output (the converter applied to its own input should be a no-op) | Tighten persona; investigate which fields differ. Often signals a non-deterministic decision the persona shouldn't be making. | Not yet |
| `T2-REVERSE-DIVERGENCE` | T2 | Reverse-translated COBOL is structurally missing elements present in the original (paragraphs, EXEC SQL blocks, FILE STATUS branches, DISPLAY targets) | The forward translation lost information. Investigator triages the missing element; re-prompt code-author with the specific gap. | Not yet |
| `T2-REVERSE-OVER-HELPFUL` | T2 | Reverse-translated COBOL has structural elements **not** present in the original | Forward translation hallucinated behavior, OR reverse-translator invented. Investigator distinguishes via the Java module. | Not yet |
| `T2-PARTIAL-COVERAGE` | T2 | Some golden-master assertions pass, others don't (score < 1.0) | Decompose: identify failing assertion, re-prompt only that path | Not yet |
| `T3-RUN-DRIFT-BYTE` | T3 | 3 runs of identical input produce byte-different output | Tighten context pack; if AST-equivalent it's acceptable | Not yet |
| `T3-RUN-DRIFT-SEMANTIC` | T3 | 3 runs produce semantically different code (failing AST equivalence) | Tighten persona; investigate non-determinism source | Not yet |
| `T3-KVOTE-DIVERGENCE` | T3 | K-vote across N=5 runs cannot reach majority (≥0.6 agreement threshold) on critical contract fields | Critical fields with low agreement are listed in `kvote_metadata.field_agreement`; re-prompt persona with the divergent field examples. If persists → Investigator triage. | Not yet |
| `T4-COST-OVERRUN` | T4 | Token cost exceeds per-file budget | Re-chunk; if persists → human review | Not yet |
| `T4-TIMEOUT` | T4 | Wall-clock exceeds per-file budget | Re-chunk; if persists → escalate | Not yet |
| `INVESTIGATE-ALTER` | T1 | Source uses COBOL `ALTER` statement (dynamic GO TO target rebinding) | Investigator agent proposes alternate angles; log each wave | Not yet |
| `INVESTIGATE-DYNAMIC-GOTO` | T1 | Source uses computed/dynamic GO TO | Investigator agent proposes alternate angles; log each wave | Not yet |
| `INVESTIGATE-EXEC-CICS` | T1 | Source uses EXEC CICS (not in step-1 scope yet — but still investigated, not stickered) | Investigator proposes angles; if blocked, log evidence | Not yet |
| `INVESTIGATE-EXEC-DLI` | T1 | Source uses EXEC DLI / IMS | Investigator proposes angles; if blocked, log evidence | Not yet |
| `INVESTIGATE-EXEC-MQ` | T1 | Source uses EXEC MQ | Investigator proposes angles; if blocked, log evidence | Not yet |
| `BLOCKED-<concept>-AFTER-<N>-WAVES` | T1 | Investigator exhausted creative angles. Terminal state. | None — written to investigation log; file deferred to a future wave with explicit rationale | Not yet |

## Convergence criteria for industrialization

The catalog is considered *stable* when:

1. ≥10 distinct slices have been converted with `acceptance/matrix.json` entries.
2. No new tag has been added in the last 3 slices.
3. Tag distribution across the last 3 slices is statistically similar (no surprise mode appears).
4. ≤10% of files fall into `BLOCKED-*` for the in-scope sub-corpus.
5. Every `BLOCKED-*` entry has a populated `investigation` log with ≥3 distinct wave attempts (see "BLOCKED is earned" below).

Until then, this is a moving target. That is expected and desirable during research.

## BLOCKED is earned, not declared

There is NO `OUT-OF-SCOPE` classification on this project. See [`docs/HARNESS-DESIGN.md`](docs/HARNESS-DESIGN.md) and the project memory `feedback-creative-exhaustion` for the principle.

Lifecycle of a failure mode:

```
INVESTIGATE-<concept>     ← active; the Investigator agent is proposing new angles each wave
        │
        ▼ (after N waves with distinct approaches and exhausted creative attempts)
BLOCKED-<concept>-AFTER-<N>-WAVES
```

A `BLOCKED-*` entry without a populated `investigation` log of ≥3 distinct attempts is itself a gate failure. The harness will refuse to write that tag.

The investigation log lives at `acceptance/investigations/<concept>.json`:

```json
{
  "concept": "ALTER",
  "first_observed": "2026-MM-DD",
  "investigation": [
    {
      "wave": 1,
      "approach": "Re-read source; check if ALTER targets are statically determinable via dataflow",
      "result": "All 3 ALTER statements have exactly 2 possible runtime targets; LLM proposed a switch with the target as the discriminant",
      "verdict": "candidate — try implementing"
    },
    {
      "wave": 2,
      "approach": "Implement switch-discriminant approach; run against sample data",
      "result": "Output passes T1 but T2 differs by 1 record — discriminant tracking lost one case",
      "verdict": "partial — needs reachability proof"
    },
    {
      "wave": 3,
      "approach": "Add Investigator-proposed flag-tracking pre-pass to enumerate reachable ALTER targets",
      "result": "T2 now passes; T3 drift remains; investigate cache invalidation",
      "verdict": "candidate — iterate"
    }
  ],
  "status": "blocked" | "resolved" | "investigating",
  "blocked_target_wave": "wave-4 SQL introduction; revisit"
}
```

## Process

- A new failure mode discovered during validation MUST be added here before any code that detects it is merged.
- The validator's emitted tags MUST be a subset of tags in this file. Unknown tags = bug.
- When a failure mode becomes obsolete (e.g., the converter learns the pattern), mark it `RESOLVED` with the date and a link to the fixing commit; do not delete the row.
