# Angle 004 — Middleware Context

**Slug:** `middleware-context`

**The question:** Does the construct depend on a middleware whose documentation pins exact semantics? If yes, what does that doc say?

**The premise:** Many COBOL constructs aren't really COBOL — they're calls into middleware that COBOL only happens to host. `EXEC SQL` is DB2's wire protocol surfaced in COBOL. `EXEC CICS` is CICS's transaction manager calling COBOL. `EXEC DLI` is IMS. `EXEC MQ` is the queue. The COBOL is the carrier; the middleware defines the semantics. Read the middleware docs, not COBOL specs.

**Inputs to consult:**

- IBM DB2 SQL Reference (for `EXEC SQL` blocks — what SQLCODE values mean, cursor semantics, etc.)
- CICS Application Programming Reference (for `EXEC CICS` verbs — RETURN, LINK, XCTL, READ, WRITE)
- IMS/DLI documentation (for `EXEC DLI`)
- WebSphere MQ Programming Reference (for `EXEC MQ`)
- AWS Mainframe Modernization documentation (sometimes documents how partners translate these to AWS services)

**When to use:**

- Anything in `EXEC <middleware> ... END-EXEC` blocks
- File handle semantics on CICS file control (`READ FILE("FOO")` vs sequential COBOL `READ`)
- Commit/rollback flow (DB2 + CICS interaction is non-trivial)
- Cursor semantics in DB2 (forward-only vs scrollable, isolation level)
- Message persistence in MQ

**Expected output shape:**

"`EXEC SQL FETCH FROM <cursor> INTO :host-var END-EXEC` per IBM DB2 SQL Reference §FETCH: advances cursor; if SQLCODE=100 (or +100 depending on edition), cursor is exhausted — equivalent to COBOL `FILE STATUS '10'` for sequential reads. Translation: Java `Stream<Row>` should return `Optional<Row>.empty()` on cursor exhaustion."

**When this angle is exhausted:**

When the middleware semantics are well-documented and the conversion is mechanical — pass to converter with the middleware-mapping note. Or when the construct uses an undocumented/internal middleware feature — escalate.

**Common failure modes of this angle:**

- "This program uses non-IBM middleware whose docs we can't find" — note in `result`, escalate
- "Middleware behavior is platform-dependent (e.g., differs between z/OS 2.x and 3.x)" — pick the most likely platform, document the assumption
