# Angle 007 — I/O Contract Preservation

**Slug:** `io-contract`

**The question:** What's the simplest Java implementation that preserves the program's input/output contract, even if the internal logic differs from the COBOL?

**The premise:** Sometimes the COBOL is doing something convoluted to achieve a simple I/O effect (read this file, transform records, write a different file; or accept these inputs, produce these outputs). If we can pin down the I/O contract precisely, we can rewrite the internals in idiomatic Java rather than transliterating COBOL line-by-line. **Equivalence-by-output, not equivalence-by-mechanism.**

**Inputs to consult:**

- JCL — DD statements define input/output datasets and their record layouts
- Copybooks — define exact input/output record shapes
- Sample data files (`app/data/EBCDIC/` or `app/data/ASCII/`) — actual input bytes
- The PROCEDURE DIVISION's `STOP RUN` / `EXIT PROGRAM` — what does the program return?
- Any external CALL statements — what's the contract with the called program?

**When to use:**

- The COBOL uses an idiom (ALTER, computed GO TO, PERFORM THRU with mid-paragraph entry) that's hard to mechanically translate
- The I/O contract is clear from external sources (JCL + copybooks) even when the internal logic is opaque
- We want to produce a working Java program that satisfies the same JCL invocation contract, even if the internal algorithm differs

**Expected output shape:**

"The program reads CARDFILE (150-byte fixed records, COPY CVACT02Y), DISPLAYs each record's contents to SYSOUT, and exits with RC=0 unless file I/O errors. The JCL feeds AWS.M2.CARDDEMO.CARDDATA.PS as input. Internal complexity (multi-paragraph PERFORM with explicit file status branching) can be replaced with a Java try-with-resources + BufferedReader loop. I/O parity preserved: same input bytes → same DISPLAY output."

**When this angle is exhausted:**

When the program has no clear I/O contract (e.g., it's a library called by other COBOL programs with complex linkage), or when behavioral equivalence requires preserving COBOL internals because they have observable side effects (e.g., specific timing, EBCDIC encoding artifacts). Move to author-intent or middleware-context.

**Common failure modes of this angle:**

- **Don't lose COBOL-specific behaviors that are silently load-bearing.** E.g., COBOL's `MOVE` truncates without warning; a "cleaner" Java translation that throws on overflow would be incorrect. The I/O might *look* the same but break under edge cases. Document any internal behavior change.
- "The program has side effects beyond I/O (e.g., writes to a log file, updates a shared in-memory table)" — those aren't captured by I/O contract alone; expand the contract or move to a different angle
- "Reimplementation produces different SQLCODE values for the same input" — that's a contract violation in the SQL semantics dimension; not pure I/O
