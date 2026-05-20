# RESULTS — per-wave baseline measurements

Append-only log of each wave's pipeline run. The honest record of where Codex
actually lands without our specialist agents.

---

## Wave 1 — CBACT02C (2026-05-20)

### Configuration

| Setting | Value |
|---|---|
| Source | `corpus/CardDemo/app/cbl/CBACT02C.cbl` (129 LOC code) |
| Pipeline phases run | F3 context-pack, F4 golden-master, F5 convert, F6 validate |
| Model | `gpt-5.5` |
| Reasoning effort | `high` |
| Temperature | `0` |
| Specialist agents wired | **none** (this is the pre-specialist baseline) |
| Run ID | `20260520-111743-d290cbbb` |

### Cost

| Metric | Value |
|---|---|
| Tokens used | **34,782** |
| Wall-clock | ~4–5 min |
| Java files emitted | 13 |
| Generated lines of Java | ~580 |
| Java-LOC per COBOL-LOC | ~4.5× |

### Acceptance tier readout

| Tier | Status | Details |
|---|---|---|
| **T1 — invariants** | ✅ **pass** | Hex layout green; 2 COBOL-id-like hits (under threshold of 5; both are legitimate); provenance comments present on every file |
| **T2 — semantic equivalence** | ❌ fail (0/41) | The golden master and the validator both need work — see "What we learned" |
| **T3 — drift** | ⏭ skipped | Not yet measured; run via `app drift` |
| **T4 — economics** | ✅ pass | Per-call metric placeholder; real $-per-file added once we wrap the Codex stdout for token counts |
| **Overall** | ❌ fail (T2 blocks) | But T2 fail is a *validator quality* problem, not a *code quality* problem (see below) |

### What Codex actually produced (qualitative)

Codex produced strikingly high-quality output on the first shot with `high` effort. Notable wins:

- **Pure-domain discipline upheld.** `domain/port/CardFilePort.java` is 16 lines, depends only on a `domain/model/` type. Zero Spring or OTel imports leak into `domain/`.
- **Two ports identified correctly.** `CardFilePort` (file I/O) **and** `ExecutionOutputPort` (for the COBOL `DISPLAY` statements). The second is non-obvious; the LLM noticed that `DISPLAY` is a separate concern from file reads and gave it its own port.
- **Port factory pattern** (`CardFilePortFactory` + `FixedWidthCardFilePortFactory`) for late-binding the file path. Not a single-implementer interface violation — there's a real wiring need.
- **Provenance comments per method** with accurate COBOL line ranges. E.g., `// from COBOL lines 88-112` on the `readNext()` method.
- **OTel instrumentation per crossing**, with standard semantic attributes (`file.path`, `file.access.mode`, `cobol.source.program`, `cobol.source.line.range`). Spans wrap try-with-resources and propagate errors via `recordException` + `setStatus(ERROR)`.
- **File status codes mapped faithfully**: `"00"` success, `"10"` EOF, `"99"` IO error — matching COBOL convention.
- **`CardRecord` as a Java 17 record** with `RECORD_LENGTH = 150`, `fromFixedWidth(...)` parser, and `toCobolDisplay()` reconstructor. The reconstructor makes the record round-trippable against the original COBOL output format.
- **Batch entry point as Spring Boot `CommandLineRunner`** with proper `SpringApplication.run(...)` and span instrumentation including `process.command` attribute.
- **`Beans.java` for DI wiring** confined to `infra/config/`, with `@Bean` factories matching the use case's constructor.

### What broke (and why it's not Codex's fault)

T2 reported 0/41 assertions matched. Two root causes, both in our code:

1. **`F4-GM-OVERINCLUSIVE` (observed).** The golden-master phase walks `source_file.parent.parent` looking for sibling `jcl/`, `ddl/`, `dcl/` directories. For `app/cbl/CBACT02C.cbl`, that resolves to `app/` — and `app/jcl/` contains JCL for the *entire* CardDemo corpus (50+ files), so 41 of them got pulled in as assertions about programs that have nothing to do with CBACT02C. Fix: only include JCL where the relevant `EXEC PGM=` references the source program; for the cpy dir, only pull copybooks the source actually `COPY`s.
2. **`F6-T2-NAIVE` (observed).** The T2 validator does naive string-token matching of feature descriptions against the Java output. It's a stand-in. The real T2 needs either an LLM-as-judge check or a structural/semantic check (e.g., do the use-case methods read the same DD names the JCL specifies?). Either is non-trivial; both are roadmap.

### What this tells us about the project

- **The first-shot baseline is much closer to passing T1 than I expected.** With `high` reasoning effort and a rich context pack, Codex emits structurally correct hex+OTel Java on a clean batch COBOL source. The "Codex won't follow architectural constraints" worry is largely refuted at this complexity.
- **The pipeline's value is therefore on the gates, not the converter prompt.** Per KNOWLEDGE.md §9.10: the LLM is the noisy generator; the gates are the deterministic filter. With T1 already green, the next investment should go to the T2/T3 gates, not into engineering the converter to be smarter.
- **Single-file batch COBOL with file I/O is a near-solved problem** at this prompt + effort. The hard cases will surface at SQL (wave 4) and multi-program orchestration (wave 3).

### Decisions taken from this wave

1. Keep the converter persona as-is for the next 2 waves; we measure how generalizable it is on harder slices before tuning.
2. Tighten the golden-master phase to use only sub-app-specific or program-specific files. Don't walk up the tree past the immediate sub-application root.
3. Replace the naive T2 validator with a structural-semantic check; first version: per `EXEC SQL` block, assert one method on a driven port; per JCL `EXEC PGM=` line, assert one adapter is wired; per COPY, assert a corresponding domain model exists.
4. Add a wall-clock measurement and token count to `codex_response.json` (T4 metrics).
5. Don't ship the cheap specialist agents from §9.9 yet. We don't need them on a wave-1 success. Add them when wave 2 or 3 produces a T1 failure that's not trivially fixable by re-prompting.
