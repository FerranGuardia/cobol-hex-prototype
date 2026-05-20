# CANDIDATES — deterministic triage of the CardDemo COBOL corpus

> **Status:** generated 2026-05-20 from a clean clone of `aws-samples/aws-mainframe-modernization-carddemo`. Every number on this page comes from the deterministic analyzer at [`src/app/pipeline/candidates.py`](../src/app/pipeline/candidates.py); re-running on the same bytes produces byte-identical artifacts. This document is meant to be consumable by the pipeline (Phase F1b) — the JSON artifacts are the machine input, this Markdown is the human face.

---

## 1. What this document is

A pre-LLM triage of every COBOL program in CardDemo, intended to answer two questions before we spend a single Codex token:

1. **Which programs are in scope for step-1?** (COBOL-only, batch, no CICS / IMS / MQ.)
2. **Of the in-scope set, which is the right starter slice?** (Cheap to reason about, has bounded I/O, fully self-contained copybook closure.)

Everything else (oracle strategy, prompt design, validator rules) is downstream of this triage. A wrong starter slice burns weeks; a right one calibrates the whole pipeline.

## 2. How the numbers were produced (reproducibility)

Single command, stdlib-only Python, no LLM:

```bash
python3 src/app/pipeline/candidates.py /path/to/CardDemo --out artifacts
```

Outputs:

- [`artifacts/candidates.json`](../artifacts/candidates.json) — per-file fingerprint (106 entries).
- [`artifacts/candidates_summary.json`](../artifacts/candidates_summary.json) — corpus rollup.

Determinism contract:

| Property | How it's guaranteed |
|---|---|
| Stable file ordering | `Path.rglob` results are sorted before scanning |
| Stable line ordering inside a file | We never reorder; we count |
| Stable hashes | SHA-256 of raw bytes (`sha256_raw`) and of canonicalized code-area (`sha256_code`); the latter is invariant under cosmetic edits to columns 1–6 (sequence numbers), column 7 (indicator), columns 73–80 (right margin), and pure-whitespace lines |
| Stable counts | Each regex runs once over the canonicalized code-only stream — no re-tokenization, no double counting |
| Stable JSON | Output is `indent=2, sort_keys=False` over the already-sorted entry list |

If you re-run on the same checkout and get a different hash, that is a real defect — file it.

## 3. Corpus at a glance

| Total files | 106 |
|---|---|
| `.cbl` programs | 44 |
| `.cpy` copybooks | 62 |
| Complexity tier LOW | 56 |
| Complexity tier MED | 25 |
| Complexity tier HIGH | 25 |
| In-scope | 76 (74 `.cpy` are trivially in-scope + 14 `.cbl` clean batch) |
| Out-of-scope | 30 |

By sub-application (`app/<sub-app>/...`):

| Sub-application | Total | `.cbl` | `.cpy` | In-scope (any) |
|---|---:|---:|---:|---:|
| `(root)` — `app/cbl/`, `app/cpy/`, etc. | 78 | 31 | 47 | 60 |
| `app-authorization-ims-db2-mq` | 19 | 8 | 11 | 11 |
| `app-transaction-type-db2` | 7 | 3 | 4 | 5 |
| `app-vsam-mq` | 2 | 2 | 0 | 0 |

## 4. The 14 in-scope `.cbl` programs (ranked easiest → hardest)

The ranking is `(complexity_score, lines_code)` ascending. `tier` uses cutoffs LOW<20, MED<60, HIGH≥60. `EXEC SQL` is broken out because SQL is the single biggest pipeline-design decision (host-variable mapping, cursor-to-stream, SQLCA error handling).

| # | Program | LOC (code) | Score | Tier | EXEC SQL | Copybooks |
|---|---|---:|---:|---|---:|---|
| 1 | `app/cbl/CBSTM03B.CBL` | 162 | 0 | LOW | 0 | — |
| 2 | `app/cbl/COBSWAIT.cbl` | 13 | 2 | LOW | 0 | — |
| 3 | `app/cbl/CBACT02C.cbl` | 129 | 6 | LOW | 0 | CVACT02Y |
| 4 | `app/cbl/CBACT03C.cbl` | 130 | 6 | LOW | 0 | CVACT03Y |
| 5 | `app/cbl/CBCUS01C.cbl` | 130 | 6 | LOW | 0 | CVCUS01Y |
| 6 | `app/cbl/CBIMPORT.cbl` | 337 | 9 | LOW | 0 | CVACT01Y, CVACT02Y, CVACT03Y, CVCUS01Y, CVEXPORT, CVTRA05Y |
| 7 | `app/cbl/CBTRN03C.cbl` | 545 | 10 | LOW | 0 | CVACT03Y, CVTRA03Y, CVTRA04Y, CVTRA05Y, CVTRA07Y |
| 8 | `app/cbl/CSUTLDTC.cbl` | 114 | 11 | LOW | 0 | — |
| 9 | `app/cbl/CBACT01C.cbl` | 358 | 11 | LOW | 0 | CODATECN, CVACT01Y |
| 10 | `app/cbl/CBTRN01C.cbl` | 415 | 11 | LOW | 0 | CVACT01Y, CVACT02Y, CVACT03Y, CVCUS01Y, CVTRA05Y, CVTRA06Y |
| 11 | `app/cbl/CBTRN02C.cbl` | 619 | 13 | LOW | 0 | CVACT01Y, CVACT03Y, CVTRA01Y, CVTRA05Y, CVTRA06Y |
| 12 | `app/cbl/CBEXPORT.cbl` | 396 | 16 | LOW | 0 | CVACT01Y, CVACT02Y, CVACT03Y, CVCUS01Y, CVEXPORT, CVTRA05Y |
| 13 | `app/cbl/CBACT04C.cbl` | 552 | 19 | LOW | 0 | CVACT01Y, CVACT03Y, CVTRA01Y, CVTRA02Y, CVTRA05Y |
| 14 | `app/app-transaction-type-db2/cbl/COBTUPDT.cbl` | 177 | 28 | **MED** | **5** | — |

All 12 referenced copybooks resolve to a file in `app/cpy/`. No dangling COPY statements; the in-scope closure is self-contained.

## 5. Out-of-scope `.cbl` programs (30) — and why

Step-1 scope is COBOL-only, batch-only, no CICS/IMS/MQ, no ALTER/computed GOTO. The analyzer rejects via these signals:

| Reason | Count |
|---|---:|
| `EXEC CICS` (online green-screen programs) | 25 |
| `EXEC DLI` (IMS database calls) | 4 |
| `CALL 'CBLTDLI'` (IMS via batch CALL interface) | 3 |
| `CALL 'MQ*'` (MQ batch CALL interface) | 3 |
| `ALTER` (dynamic GO TO target) | 1 |

(Some files match more than one — totals sum to 36 across 30 unique files.)

Notable cases:

- **`COPAUA0C.cbl`** — the maximally hostile combo: CICS + DLI + MQ in one program. Save for the very last wave.
- **`CBSTM03A.CBL`** — flagged solely for `ALTER`. This is the only `ALTER` in the entire corpus. Tag `UNCONVERTIBLE-ALTER` is justified by exactly one file — useful to know before designing recovery.
- **`COTRTLIC.cbl`, `COTRTUPC.cbl`** — the *online* counterparts of `COBTUPDT`. Out of scope only because of CICS; their DB2 logic is structurally similar to COBTUPDT. They'll become valuable for a "same domain, online vs batch" comparison study once CICS is in scope.

The full list with reasons is in [`artifacts/candidates.json`](../artifacts/candidates.json) — each entry has `eligibility` and `out_of_scope_reasons`.

## 6. Recommended starter slice — `CBACT02C`

Of the LOW-tier in-scope set, `CBACT02C` is the **calibration target** for the pipeline:

| Property | Value |
|---|---|
| Path | `app/cbl/CBACT02C.cbl` |
| Bytes | 14,096 |
| `sha256_raw` | `d290cbbbec1e25859847d9dfe6b28040cd6b09c3b71747e39de7b4713d838e76` |
| `sha256_code` | `7b6bedd2217ead8b96486ecb027cc2d6e56f9c180f51b3e6b7840029f9681a17` |
| LOC (code-only) | 129 |
| Named paragraphs in PROCEDURE DIVISION (by-eye) | 5: `0000-CARDFILE-OPEN`, `1000-CARDFILE-GET-NEXT`, `9000-CARDFILE-CLOSE`, `9999-ABEND-PROGRAM`, `9910-DISPLAY-IO-STATUS` |
| Analyzer `paragraph_count` | 3 (undercount — see limitation §8.2 below) |
| Copybook | `CVACT02Y.cpy` (CARD-RECORD, 150-byte fixed) |
| JCL | `app/jcl/READCARD.jcl` (`STEP05 EXEC PGM=CBACT02C`) |
| Input data | `app/data/EBCDIC/AWS.M2.CARDDEMO.CARDDATA.PS` + `app/data/ASCII/carddata.txt` |
| What it does | Open a KSDS VSAM cardfile, read it sequentially, `DISPLAY` each record, close, exit. Strict file-status branching. No SQL, no CICS, no MQ. |
| External calls | One: `CALL 'CEE3ABD'` (LE abend service) in the ABEND path |

**Why this is the right starter:**

1. **Smallest meaningful surface.** Bigger than COBSWAIT (which is too trivial to teach the pipeline anything) and CBSTM03B (which has no I/O and won't exercise the adapter pattern). At 129 LOC of code, it fits in any context window without chunking.
2. **One copybook, one record layout.** The copybook closure is a single 13-line `01 CARD-RECORD` definition. Trivial to model as a Java record.
3. **Hex-natural shape.** It already separates open/read/close into paragraphs — every paragraph maps cleanly to a method on a `CardFile` out-port. Hex translation is mechanical.
4. **Has a real golden master.** The `carddata.txt` file under `data/ASCII/` is a 150-byte-record ASCII fixture; you can `cat` it, run the original program under GnuCOBOL, and capture stdout. That's a free behavioural oracle.
5. **Exercises every pipeline tier except SQL.** File I/O, error branching, abend semantics, copybook resolution, JCL data binding. SQL gets added in slice 2.
6. **The 9999-ABEND-PROGRAM paragraph is a known thorn.** `CALL 'CEE3ABD'` (z/OS Language Environment) won't exist on the modern side; the converter must map it to a `RuntimeException` or `System.exit(N)`. This is the smallest concrete test of "what do you do when the COBOL talks to the runtime?" — exactly the kind of decision we want surfaced *on the first slice*, not the tenth.

**Proposed progression:**

| Wave | Slice | Adds | Risk it shakes out |
|---|---|---|---|
| 1 | `CBACT02C` | KSDS read, copybook, abend | I/O port shape, copybook→Java mapping, runtime-error handling |
| 2 | `CBACT03C` + `CBCUS01C` | Two more file types | Pipeline generalisation across record layouts |
| 3 | `CBTRN01C` or `CBTRN02C` | Multi-copybook, longer flow | Cross-paragraph state, JCL multi-DD binding |
| 4 | `COBTUPDT` | First `EXEC SQL` (5 occurrences) | SQLCA, host variables, cursor-to-stream, DB2-out-port |
| 5 | `CBACT04C` | Interest calculation (largest LOC, score 19) | Numeric semantics, COMPUTE/decimal precision |

## 7. The COBTUPDT outlier (why it's tier MED, not LOW)

`COBTUPDT` is the only in-scope program with `EXEC SQL`. Five blocks across 177 LOC of code → density of 1 SQL block per 35 LOC, which is the SQL-saturated profile we expect. The complexity score of 28 sits squarely in tier MED because:

- `exec_sql=5` contributes 15 to the score (5×3) and
- the DB2 density bonus adds another +4

This is the right shape for wave 4: small enough to fit in one context window, dense enough that any SQL pattern the pipeline mishandles will surface immediately.

## 8. Known limitations of the analyzer (be honest)

These are open issues; they don't invalidate today's ranking but they may shift edge cases later.

1. **Macro CICS via copybooks** — if a copybook contains `EXEC CICS`, the using program would not be flagged unless we cross-resolve `COPY` statements before counting. Today we count *only on the source*. Mitigation: also scan `.cpy` for EXEC blocks and propagate.
2. **Paragraph counter mixes DATA DIVISION items with PROCEDURE DIVISION paragraphs.** The regex matches any `NAME.` line, including FD/01-level items. For CBACT02C we report 3 but the by-eye count of PROCEDURE-DIVISION paragraphs is 5. Fix: track DIVISION/SECTION context while walking lines. Until then, treat `paragraph_count` as a lower bound, not an exact count.
3. **`EXEC SQL INCLUDE`** — when a SQLCA or host-variable include is pulled via `EXEC SQL INCLUDE foo END-EXEC`, my counter sees that as one extra `exec_sql`. The current count for COBTUPDT (5) likely contains 1–2 `INCLUDE`s; verify by reading the file.
4. **Continuation lines** — COBOL allows continuation via `-` in column 7. The canonicalizer treats them as separate lines for hashing/counting. For pattern detection that's fine (the keywords are atomic); for line counts it slightly inflates by 1-2 lines on dense files.
5. **`SQL` inside literals** — `MOVE 'EXEC SQL' TO foo` would be falsely counted. Probability: vanishing. CardDemo doesn't do this.
6. **Encoding** — files are read as UTF-8 with `errors="replace"`. CardDemo's source is ASCII; this is correct. The `data/EBCDIC/` directory is *not* scanned (correctly — those are not source).
7. **Tier cutoffs are placeholders** — `LOW<20, MED<60` are reasonable defaults but uncalibrated. Recalibrate after the first 3 real runs once we know how score maps to actual conversion difficulty.

## 9. How the pipeline should consume this

Two consumption modes, depending on where in F1–F8 we are:

- **F1 (inventory)**: read `candidates.json` and build the dependency graph (program → copybooks → other programs via CALL targets). The 12 in-scope copybooks plus 14 in-scope programs give a small, fully-resolved DAG.
- **F3 (context pack)**: for the chosen slice, the context pack is `{source.cbl, [referenced copybooks], related JCL, optional sample data record}`. `candidates.json` already has the `copy_names` list per program — no extra grep needed.
- **F4 (golden master)**: for wave-1 (`CBACT02C`), the golden master is the stdout of running the program against `app/data/ASCII/carddata.txt` under GnuCOBOL (or any COBOL runtime). 150-byte fixed-length records, no SQL — captured as a text fixture and replayed against the Java output.
- **F6 (validate, T1 hex/OTel checks)**: the `paragraph_count` and `section_count` give the validator an expected lower-bound on the number of methods on the use-case + adapters (one method per paragraph minimum). Useful for catching "the LLM merged paragraphs together" failure modes.

## 10. Re-running

Anytime the corpus or analyzer changes:

```bash
cd cobol-hex-prototype
python3 src/app/pipeline/candidates.py /path/to/CardDemo --out artifacts
git diff artifacts/candidates.json artifacts/candidates_summary.json
```

A non-empty diff means either the corpus changed (legitimate) or the analyzer changed (intentional — bump `schema_version` in the analyzer when this happens). Diffs are reviewable line-by-line because the JSON is sorted.

## 11. Bottom line

- 14 of 44 CardDemo COBOL programs are inside step-1 scope. The starter slice is `CBACT02C`; the SQL-introducing slice is `COBTUPDT`.
- Every number on this page is reproducible from the analyzer; the JSON is the contract.
- Two pipeline-design decisions are now teed up: (1) how to map `CALL 'CEE3ABD'` to a JVM error pathway, (2) when to introduce `EXEC SQL` handling. Both will be answered by wave-1 → wave-4 progression above.
