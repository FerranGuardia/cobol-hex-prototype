# COMPARISON — wave-2 Java vs original COBOL (CBACT02C)

> Honest LLM-as-judge review of `artifacts/20260520-131325-d290cbbb/output/` against `corpus/CardDemo/app/cbl/CBACT02C.cbl`. Performed 2026-05-20 by reading the COBOL source, the wave-2 Java, the contract, and the copybook. **No external Java reference was available** — see "Comparison context" for why.
>
> This is a research/eval artifact, not a pipeline output. Findings here drive updates to [SPEC.md](../SPEC.md), [FAILURES.md](../FAILURES.md), and [prompts/code-author.md](../prompts/code-author.md) — the actual pipeline does not depend on this document.

---

## What the COBOL actually does

Reads VSAM KSDS `CARDFILE`, displays each 150-byte record to stdout, abends on I/O error via `CEE3ABD`. 87 lines of PROCEDURE DIVISION across 5 paragraphs:
- `0000-CARDFILE-OPEN` — `OPEN INPUT`, check FILE STATUS, abend on non-'00'
- `1000-CARDFILE-GET-NEXT` — `READ` next record, branch on FILE STATUS ('00' / '10' / error), set EOF flag or abend
- `9000-CARDFILE-CLOSE` — `CLOSE`, check FILE STATUS, abend on non-'00'
- `9999-ABEND-PROGRAM` — `CALL 'CEE3ABD' USING ABCODE, TIMING` (terminal LE call, ABCODE=999)
- `9910-DISPLAY-IO-STATUS` — formats FILE STATUS for display, with bit-level handling when status is non-numeric or starts with '9'

File declared `ORGANIZATION IS INDEXED ACCESS MODE IS SEQUENTIAL RECORD KEY IS FD-CARD-NUM`. Records are 150 bytes (16-byte key + 134-byte data).

## What wave-2 Java actually does

13 files, 636 LOC, hex-architecture layout, OTel-instrumented, provenance-tagged. Functionally close to the COBOL on the ASCII fixture, with **4 measurable semantic drifts** and **3 stylistic / over-engineering concerns**.

## Strict improvements over wave-1 / over the "ok-ish" baseline

1. **Schema-valid contract emitted first try** — `contracts/public-contract.code-author.json` validates against `schemas/public-contract.schema.json` with zero errors.
2. **Source-anchor SHAs verified correct** — COBOL + copybook SHA-256 byte-equal to actuals.
3. **Faithful paragraph mapping** — explicit `abendProgram()`, `displayIoStatus()`, `handleIoError()` helpers mirror COBOL paragraphs `9999-ABEND-PROGRAM`, `9910-DISPLAY-IO-STATUS`, FILE-STATUS branches.
4. **SPEC-compliant span naming** — `<package>.<usecase>.<operation>` format on every span.
5. **SPEC-compliant class naming** — `Cbact02cBatchRunner` per SPEC §Soft conventions.
6. **Line-accurate provenance** on every Java method tying back to specific COBOL line ranges.

## Real semantic drifts (4)

### D1 — VSAM-INDEXED reads collapsed to line-delimited text reads
- **Where:** [adapter/out/file/FixedWidthCardFileAdapter.java:71](../artifacts/20260520-131325-d290cbbb/output/com/example/cobol/cbact02c/adapter/out/file/FixedWidthCardFileAdapter.java#L71) uses `BufferedReader.readLine()`.
- **Drift:** COBOL declares `ORGANIZATION IS INDEXED ACCESS MODE IS SEQUENTIAL RECORD KEY IS FD-CARD-NUM`. The Java implements newline-delimited text reads, which works on the ASCII fixture (`carddata.txt`) only because that file happens to be newline-delimited. A real VSAM file is fixed-width binary with no newlines.
- **Severity:** medium. Works on corpus, wrong in general. The LLM made a convenience simplification.
- **Catches:** harness mechanical-extractor (Phase A, next turn) — scan COBOL `SELECT ... ORGANIZATION IS X` and assert Java adapter implements matching read semantics.
- **Failure tag:** `T2-FILE-ORG-DRIFT`.

### D2 — `CEE3ABD` process-termination becomes a catchable `IllegalStateException`
- **Where:** [application/usecase/ReadCardFileUseCase.java:56](../artifacts/20260520-131325-d290cbbb/output/com/example/cobol/cbact02c/application/usecase/ReadCardFileUseCase.java#L56).
- **Drift:** COBOL `CALL 'CEE3ABD' USING ABCODE, TIMING` terminates the Language Environment process with code 999. The Java throws `IllegalStateException("CBL-ABEND-999")`, which any caller can catch. The semantic contract — "abend is terminal, never returns" — changed.
- **Severity:** medium-high. If anything between the use case and `main()` catches RuntimeException, behavior diverges from COBOL.
- **Catches:** harness check (Phase B) — scan COBOL for `CALL 'CEE3ABD'` (or any `CEE3xxx`); assert Java's corresponding code path calls `System.exit(...)` or throws an error that is documented as uncatchable (e.g., a custom `Error` subclass).
- **Fix:** persona rule + harness check.
- **Failure tag:** `T2-ABEND-CATCHABLE`.

### D3 — Duplicate "ABENDING PROGRAM" line in close-error path
- **Where:** [application/usecase/ReadCardFileUseCase.java:63-68](../artifacts/20260520-131325-d290cbbb/output/com/example/cobol/cbact02c/application/usecase/ReadCardFileUseCase.java#L63-L68). `handleIoError` writes "ABENDING PROGRAM", then calls `abendProgram()` which writes "ABENDING PROGRAM" again.
- **Drift:** the close-error path emits the abend line **twice**. The COBOL emits it once.
- **Severity:** low (output line duplicated, behavior otherwise identical). Triggered only on close-error.
- **Catches:** T2-equivalence golden-master test against curated `expected-output.txt` — would surface the extra line.
- **Fix:** persona rule (don't write the abend line in `handleIoError`; let `abendProgram()` own it).
- **Failure tag:** `T2-DUPLICATED-OUTPUT`.

### D4 — ASCII byte values where COBOL would use EBCDIC
- **Where:** [domain/model/FileStatusFormatter.java:19](../artifacts/20260520-131325-d290cbbb/output/com/example/cobol/cbact02c/domain/model/FileStatusFormatter.java#L19) does `(int) stat2` to format the second byte of a file status as 3-digit decimal.
- **Drift:** COBOL on z/OS works in EBCDIC: byte '9' = 0xF9 = 249, so status "9x" displays as `9249` for x='9'. Java works in ASCII: byte '9' = 0x39 = 57, displaying `9057`. Same logical operation, different output bytes.
- **Severity:** low for this pipeline (the corpus is ASCII; the system is internally consistent). Becomes important if the pipeline is ever fed mainframe-native EBCDIC data.
- **Catches:** harness check — when COBOL `MOVE <byte> TO <binary>` is followed by `DISPLAY`, the Java must document the charset assumption (`// charset: ASCII (corpus assumption)`) or perform an explicit EBCDIC-equivalent byte conversion.
- **Fix:** persona rule (require charset comment when byte-twiddling for display).
- **Failure tag:** `T2-CHARSET-IMPLICIT`.

## Stylistic / over-engineering concerns (3)

### S1 — `CardFilePortFactory` declared as a port
- **Where:** Both `domain/port/CardFilePortFactory.java` (declared as port in contract with `justification: "crosses-external-boundary"`) and `adapter/out/file/FixedWidthCardFilePortFactory.java`.
- **Concern:** Factories don't cross external boundaries — they construct things. The hex pragmatism rule (SPEC §Hex pragmatism rule) requires a port to cross a boundary, have ≥2 implementations, or switch at runtime. None apply. Likely `T1-OVER-ABSTRACTION`.
- **Catches:** harness check on contract `ports[].justification` validity.
- **Failure tag:** existing `T1-OVER-ABSTRACTION`.

### S2 — `CardRecord` lost wave-1's `record` idiom
- **Where:** [domain/model/CardRecord.java](../artifacts/20260520-131325-d290cbbb/output/com/example/cobol/cbact02c/domain/model/CardRecord.java) — verbose `final class` with explicit constructor + 7 accessors.
- **Concern:** Wave-1 used `record CardRecord(...)` — wave-2's verbose form is ~30 LOC longer for no semantic gain, and loses Java's auto-generated `equals`/`hashCode`/`toString`. Worth adding a persona note to prefer `record` for value objects.
- **Failure tag:** soft — convention guideline in SPEC §Soft conventions.

### S3 — `Path` leaks into the application layer
- **Where:** [application/usecase/ReadCardFileUseCase.java:33](../artifacts/20260520-131325-d290cbbb/output/com/example/cobol/cbact02c/application/usecase/ReadCardFileUseCase.java#L33) — use case method takes a `java.nio.file.Path`.
- **Concern:** Soft hex violation. The use case now knows the card data lives on a filesystem. A cleaner design: the use case takes a logical resource name (e.g., `String ddName = "CARDFILE"`) and the adapter resolves it to a filesystem location. Matches COBOL's `ASSIGN TO CARDFILE` DD name.
- **Failure tag:** new — `T1-PATH-LEAK` (or extend `T1-HEX-VIOLATION`).

## Comparison context

| Baseline | Available? | Verdict |
|---|---|---|
| AWS Java translation of CardDemo | **Not public** — verified via aws-samples search (only the COBOL repo exists) and broad GitHub search (55 unrelated hits) | Cannot directly compare |
| `abhi-ksh/aws-carddemo-modernized` | **Empty repo** — `Initial commit` with LICENSE + 63-byte README, no code | DIARY hypothesis disproved |
| Microsoft Legacy-Modernization-Agents | Cloned at `../../Legacy-Modernization-Agents/`, not run | Their pipeline produces what they label "ok-ish Java"; ours has hex + OTel + provenance which theirs doesn't enforce |
| Senior-Java-engineer hand-port | Mental model | Would use `record`, skip the factory, model `FileStatus` as a sealed hierarchy, read 150-byte fixed records (not lines). Wave-2 trades idiomatic density for literal-COBOL fidelity, per SPEC. |

## Honest verdict

Wave-2 is materially better than wave-1, plausibly better than Microsoft's baseline on rigor axes, with **4 specific semantic drifts** and **3 stylistic concerns** — all small, all fixable, all exactly what the Phase A harness checks are designed to surface.

**The research bet is intact.** None of the 4 drifts invalidate the maximalism-pipeline thesis; they validate the harness layer. The persona rewrite + schema + contract emission delivered. What remains is the deterministic catches.

## What this triggers (concrete file changes)

- [prompts/code-author.md](../prompts/code-author.md) — new §"Semantic fidelity rules" with the 4 anti-drift rules + the 3 style rules
- [SPEC.md](../SPEC.md) — extend §Hard invariants with file-organization, abend-mapping, charset-explicitness, no-Path-leak
- [FAILURES.md](../FAILURES.md) — add `T2-FILE-ORG-DRIFT`, `T2-ABEND-CATCHABLE`, `T2-CHARSET-IMPLICIT`, `T2-DUPLICATED-OUTPUT`, `T1-PATH-LEAK`
- Next turn: `harness/extract/cobol_facts.py` adds extractors that flag each drift mechanically; `harness/checks/reverse_translate.py` catches paragraph-level information loss

The user's principle for the next phase: **more agents = counter; harnessing = the work.** The remaining drifts close not by adding LLM passes but by adding deterministic checks.
