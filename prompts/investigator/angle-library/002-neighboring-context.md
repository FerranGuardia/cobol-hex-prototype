# Angle 002 — Neighboring Context

**Slug:** `neighboring-context`

**The question:** What do the surrounding paragraphs, copybooks, or sibling programs in the same sub-application tell us about this construct?

**The premise:** Mainframe programs cluster. One COBOL file rarely lives alone — it's part of a sub-application with shared copybooks, shared JCL chains, and shared idioms. If paragraph X is unclear, paragraphs W and Y may use the same data structures or call patterns and clarify it. Cross-reference the LOCAL environment before consulting external references.

**Inputs to consult:**

- Other `.cbl` programs in the same sub-application (`app/<sub-app>/cbl/`)
- The shared copybooks (`app/<sub-app>/cpy/` and `app/cpy/`)
- The full JCL chain (which other steps run before/after this program in the same JCL?)
- BMS maps if the program is CICS-bound
- CSD (CICS Resource Definition) files if present

**When to use:**

- The construct looks idiomatic but unclear in isolation — a sibling program likely uses the same idiom.
- The data flow into this paragraph comes from a `01`-level record defined in a shared copybook — the copybook's field comments often clarify intent.
- Looking for "how is this normally done in this codebase?" before asking "how is this done in COBOL generally?"

**Expected output shape:**

"Paragraph 1000-CARDFILE-GET-NEXT reads from a sequential cardfile via `READ TR-RECORD`. Sibling program COTRTUPC.cbl uses the same SELECT statement structure (`FILE-CONTROL` with `ORGANIZATION IS SEQUENTIAL`) and treats `WS-INF-STATUS = '10'` as end-of-file in `2000-PROCESS-EOF`. Apply same convention here."

**When this angle is exhausted:**

When neighboring programs use the construct differently or don't use it at all — the local convention isn't informative enough. Move to language-cousins or middleware-context.

**Common failure modes of this angle:**

- "This program is the only one in its sub-application" — angle returns no signal, log and move on
- "Siblings exist but they're all written by different authors with different conventions" — note inconsistency in `result`, lower confidence
