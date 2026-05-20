# Angle 005 — Corpus Precedent

**Slug:** `corpus-precedent`

**The question:** Has someone in the open-source community already solved this conversion? Has another modernization of CardDemo (or similar COBOL) handled this exact construct?

**The premise:** We're not the first. CardDemo has been a public benchmark since AWS published it. At least three independent modernizations exist (`abhi-ksh/aws-carddemo-modernized`, `Crowdbotics-Research/BENCH-AWS-CardDemo`, `Frenzy117/aws-carddemo-rag-from-scratch`). The GnuCOBOL community has decades of legacy code conversion lore. The NIST CCVS COBOL Compiler Validation System has formal expected outputs for canonical idioms. **Don't reinvent — read what others did.**

**Inputs to consult:**

- `abhi-ksh/aws-carddemo-modernized` (https://github.com/abhi-ksh/aws-carddemo-modernized) — someone's modernized CardDemo; how did they handle this construct?
- `Crowdbotics-Research/BENCH-AWS-CardDemo` — frontier-model benchmarking; may have testcases revealing expected behavior
- `Frenzy117/aws-carddemo-rag-from-scratch` — RAG over CardDemo source; different angle
- GnuCOBOL test suite (publicly accessible) — looks for the same idiom in a working test
- NIST CCVS suite if the construct is on the COBOL-85 grammar
- Stack Overflow / IBM forums for the specific COBOL construct

**When to use:**

- The construct is recognizable as a common COBOL idiom — someone has likely modernized it
- We're unsure between two valid translations — see what others picked
- We need a reference for "what is the typical OOP shape this maps to?"

**Expected output shape:**

"abhi-ksh/aws-carddemo-modernized handles file status code branching by mapping COBOL FILE STATUS to a `FileOperationResult` enum with `SUCCESS`, `END_OF_FILE`, `IO_ERROR`. Their approach matches our wave-1 generated code (`"00"`, `"10"`, `"99"` mapping). Our converter is consistent with the broader community pattern; no change needed."

**When this angle is exhausted:**

When the construct is novel enough that no public modernization handled it (e.g., a deeply legacy bank-specific idiom), or when the references disagree wildly and we need to pick our own path. Move to language-cousins or partial-translation.

**Common failure modes of this angle:**

- "All public references treat the idiom as 'undefined behavior' and avoid it" — that's a signal the idiom is genuinely hard; document and continue
- "References modernize to incompatible shapes (one uses inheritance, another uses ADTs)" — the choice may be ours; document the tradeoff
- "The reference quality is poor (auto-generated, no tests, no commit message)" — discount the signal accordingly
