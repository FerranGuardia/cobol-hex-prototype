# Angle 001 — Author Intent (the historical anchor)

**Slug:** `author-intent`

**The question:** What was the original author trying to accomplish? Why does this code exist?

**The premise:** Every COBOL program exists because someone needed it to do something. The author had goals. Naming conventions, paragraph structure, comments, copybook choices, and JCL invocation context all encode intent. Recovering that intent is often easier than recovering exact semantics.

**Inputs to consult:**

- Inline comments at the top of the program (`* PROGRAM: ...`, `* PURPOSE: ...`)
- The `PROGRAM-ID` itself — many names are mnemonic (e.g., `COBTUPDT` = COBol Transaction UPDaTe)
- Paragraph names in `PROCEDURE DIVISION` — usually descriptive (e.g., `0000-CARDFILE-OPEN`, `1000-CARDFILE-GET-NEXT`)
- Copybook names — what data shape does the program operate on?
- The JCL that invokes the program — what dataset names are wired in/out? What's the batch step's role in the workflow?
- The sub-application README, if any

**When to use:**

- ALWAYS use as wave 1 if the prior investigation log is empty (the default opening angle per the meta-prompt).
- Use when a section of code looks alien but neighboring sections are clearly purposeful — the alien code is probably serving a specific known goal.

**Expected output shape:**

A 2–4 sentence summary of intent like: "The program reads a fixed-width VSAM cardfile sequentially, displays each record to the system console, and exits cleanly. The JCL invokes it as STEP05 of READCARD.jcl, suggesting it's a debugging / verification step in a larger batch chain."

**When this angle is exhausted:**

When the intent is well-understood and clear, but the BLOCKER remains (e.g., we KNOW what the code is trying to do, but the way it does it uses an idiom we can't translate). Move to a different angle (neighboring-context, language-cousins, partial-translation).

**Common failure modes of this angle:**

- "The PROGRAM-ID is cryptic and there are no comments" — the angle isn't useless here, but lower confidence. Continue to other angles.
- "The intent is clear but doesn't help translate" — note this in `result` and propose a more mechanical angle next.
