# FAILURES — the catalog of known failure modes

The honest face of the tool. Every documented failure tag lives here. A small, well-categorized catalog is the credibility proof; a hidden or curated-away failure is dishonesty.

> Companion to [`SPEC.md`](SPEC.md). When the spec and this catalog disagree about whether something is acceptable, this file wins. Reality beats aspiration.

---

## Status

Empty. No real runs have been executed yet. Tags below are the *scaffold* — modes we anticipate. Real tags get marked `OBSERVED` once we see them in the wild, with example artifacts.

## Catalog (scaffold)

| Tag | Tier | Trigger | Recovery | Observed |
|---|---|---|---|---|
| `T1-COMPILE-ERROR` | T1 | Generated Java does not compile | Re-prompt with `javac` error in context; max 2 retries | Not yet |
| `T1-HEX-VIOLATION` | T1 | ArchUnit detects layer dependency violation | Re-prompt with violation list; max 2 retries | Not yet |
| `T1-OTEL-MISSING` | T1 | A use-case or adapter method lacks span instrumentation | Post-pass agent inserts spans | Not yet |
| `T1-OVER-ABSTRACTION` | T1 | A single-implementer port introduced inside `application/` layer | Re-prompt with the pragmatism rule (see SPEC.md) | Not yet |
| `T1-FORMAT-DIRTY` | T1 | `google-java-format` reports diffs | Auto-fix via formatter; pass | Not yet |
| `T1-COBOL-IDIOM-LEAK` | T1 | GOTO, global state, or COBOL-style flag-driven control flow detected | Re-prompt with idiom-list | Not yet |
| `T1-NO-PROVENANCE` | T1 | Missing or malformed provenance header on a generated file | Auto-insert; warn | Not yet |
| `T2-BEHAVIOR-MISMATCH` | T2 | Generated code's output differs from golden master on a documented input | Re-prompt with the diff; if persists 2× → escalate to human | Not yet |
| `T2-PARTIAL-COVERAGE` | T2 | Some golden-master assertions pass, others don't (score < 1.0) | Decompose: identify failing assertion, re-prompt only that path | Not yet |
| `T3-RUN-DRIFT-BYTE` | T3 | 3 runs of identical input produce byte-different output | Tighten context pack; if AST-equivalent it's acceptable | Not yet |
| `T3-RUN-DRIFT-SEMANTIC` | T3 | 3 runs produce semantically different code (failing AST equivalence) | Tighten persona; investigate non-determinism source | Not yet |
| `T4-COST-OVERRUN` | T4 | Token cost exceeds per-file budget | Re-chunk; if persists → human review | Not yet |
| `T4-TIMEOUT` | T4 | Wall-clock exceeds per-file budget | Re-chunk; if persists → escalate | Not yet |
| `UNCONVERTIBLE-ALTER` | T1 | Source uses COBOL `ALTER` statement (dynamic GO TO target rebinding) | Out of scope; log; skip file | Not yet |
| `UNCONVERTIBLE-DYNAMIC-GOTO` | T1 | Source uses computed/dynamic GO TO | Out of scope; log; skip file | Not yet |
| `UNCONVERTIBLE-EXEC-CICS` | T1 | Source uses EXEC CICS (out of step-1 scope) | Out of scope; log; skip file | Not yet |
| `UNCONVERTIBLE-EXEC-DLI` | T1 | Source uses EXEC DLI / IMS (out of step-1 scope) | Out of scope; log; skip file | Not yet |
| `UNCONVERTIBLE-EXEC-MQ` | T1 | Source uses EXEC MQ (out of step-1 scope) | Out of scope; log; skip file | Not yet |

## Convergence criteria for industrialization

The catalog is considered *stable* when:

1. ≥10 distinct slices have been converted with `acceptance/matrix.json` entries.
2. No new tag has been added in the last 3 slices.
3. Tag distribution across the last 3 slices is statistically similar (no surprise mode appears).
4. ≤10% of files fall into `UNCONVERTIBLE-*` for the in-scope sub-corpus.

Until then, this is a moving target. That is expected and desirable during research.

## Process

- A new failure mode discovered during validation MUST be added here before any code that detects it is merged.
- The validator's emitted tags MUST be a subset of tags in this file. Unknown tags = bug.
- When a failure mode becomes obsolete (e.g., the converter learns the pattern), mark it `RESOLVED` with the date and a link to the fixing commit; do not delete the row.
