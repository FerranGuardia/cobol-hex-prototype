# Angle 006 — Partial Translation

**Slug:** `partial-translation`

**The question:** Can we translate the parts of this program we DO understand cleanly, isolate the part we don't into a small, well-defined hole, and convert only that residual later?

**The premise:** A failing translation often blocks the entire file. But a 237-LOC COBOL program with one bad paragraph isn't 237 LOC of unconvertible code — it's 236 + 1. Producing the 236 + an explicit gap marker is better than producing nothing. The gap is then a small, focused investigation target.

**Inputs to consult:**

- The COBOL source itself — identify the boundary of the problematic construct precisely (which lines? which paragraph?)
- The converted output so far — what compiles? what passes T1?
- The hex layout — the gap belongs in *one* layer (probably an `adapter/out/`); the rest of the layers can be complete

**When to use:**

- The blocker is localized (one paragraph, one EXEC SQL block, one CALL to an external program)
- The surrounding code translates cleanly
- We're looking for a way to make 90% progress while the 10% gap stays in INVESTIGATING

**Expected output shape:**

"The `9999-ABEND-PROGRAM` paragraph calls `CEE3ABD` (LE abend service). This is the only block needing investigation; the surrounding 200 LOC of file I/O translates cleanly to the existing FixedWidthCardFileAdapter pattern. Recommend: convert everything else; replace the abend call with `throw new IllegalStateException(\"CEE3ABD legacy abend; placeholder\")` and tag the produced method with `// INVESTIGATE-CEE3ABD-after-wave-1`. The IllegalStateException is a known controlled failure, not a stub."

**When this angle is exhausted:**

When the unconverted residual is large enough that it's the bulk of the program (>20%) — partial translation is no longer "partial", it's "mostly broken". Or when the residual touches every other component (e.g., a control-flow keyword that affects every paragraph). Move to other angles or escalate.

**Common failure modes of this angle:**

- **It is NOT a stub-shop.** The placeholder MUST be a controlled, documented failure (`throw new IllegalStateException(...)` with explanation), NOT a silent `return null` or empty method body. Stubs are banned per the no-stubs doctrine (see `FAILURES.md` + newABINA QA lessons).
- "The residual leaks across layer boundaries (e.g., the unknown construct touches both adapter/out and domain)" — that's not a localized gap; this angle doesn't apply
- "We marked it INVESTIGATE but never followed up" — the slice's classification must include a target wave for the investigation; no fire-and-forget
