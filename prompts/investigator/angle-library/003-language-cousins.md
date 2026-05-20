# Angle 003 — Language Cousins

**Slug:** `language-cousins`

**The question:** Does another procedural language (PL/I, ABAP, RPG, Fortran, JCL itself, older Java pre-NIO) handle this construct in a documented way that gives us a translation hint?

**The premise:** COBOL doesn't exist in a vacuum. Many of its constructs evolved in parallel with PL/I (IBM's other mainframe language) and have direct cousins. EBCDIC packed decimals exist in PL/I too. CICS bindings are documented across COBOL and PL/I. File status codes are standardized. When COBOL semantics are ambiguous, consult the cousin language's documentation — the IBM teams who wrote both often borrowed each other's solutions.

**Inputs to consult:**

- IBM Enterprise PL/I Language Reference (publicly available PDF)
- IBM Enterprise COBOL Language Reference
- ABAP documentation if the construct involves business data transformations (ABAP has analogous concepts)
- Fortran or older RPG references for numeric / fixed-point arithmetic quirks
- For files: JCL DD statement docs, VSAM Programmer's Guide (publicly available)

**When to use:**

- COMP-3 / packed decimal edge cases (sign nibble, overflow semantics)
- File status code interpretation (`'10'` = EOF in IBM convention but other vendors differ)
- CICS handle vs `CALL` semantics
- `OCCURS DEPENDING ON` runtime sizing rules
- Numeric overflow / truncation on `COMPUTE`

**Expected output shape:**

"IBM Enterprise PL/I 5.3 documents identical packed-decimal sign-nibble handling: 0xD = negative, 0xC/0xF = positive. The 'half-byte' overlap is intentional and pre-EBCDIC. For our converter, mapping COMP-3 to BigDecimal with explicit sign extraction matches PL/I-COBOL bi-language conventions used in IBM batch systems through the 1990s."

**When this angle is exhausted:**

When the cousin language doesn't have an equivalent construct, or when the COBOL idiom is genuinely unique (e.g., `ALTER` has no clean cousin — every modern language considers it harmful). Move to middleware-context or partial-translation.

**Common failure modes of this angle:**

- "Cousin language X handles it differently than COBOL" — useful, but don't translate to the cousin's semantics; document the divergence and continue
- "Multiple cousins disagree" — escalate to author-intent: which does THIS specific program rely on?
