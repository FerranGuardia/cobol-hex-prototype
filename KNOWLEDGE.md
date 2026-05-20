# KNOWLEDGE — sources of determinism we can mine

> "any sniped of determinism is what i seek" — Ferran, 2026-05-20
>
> Living document. Every angle of attack on the determinism problem lives here. Mark each
> entry `[ACTIVE]`, `[PROVEN]`, `[REJECTED]`, or `[TODO]` as we evolve. Lift liberally
> from other people's work — the spirit of newABINA: when a wall appears, find a window.

---

## 1. Information we can extract from a COBOL source file alone

These are *cheap*, *static*, and produce structured data that grounds the LLM. No runtime needed.

| # | Signal | Determinism it gives | Status |
|---|---|---|---|
| 1.1 | **DIVISION / SECTION / PARAGRAPH structure** — every COBOL program is a strict 4-division layout. AST is fully recoverable from text. | 100% deterministic skeleton. The Java module shape is *implied* by this skeleton. | [ACTIVE] used by F1 inventory + F3 context pack |
| 1.2 | **PIC clauses** — exact type info: width, sign, decimal alignment. | Drives Java type mapping table: `PIC X(n)`→`String(n)`, `PIC 9(n)`→`int/long`, `PIC 9(n)V9(m) COMP-3`→`BigDecimal`. | [ACTIVE] codified in `prompts/analyzer.md` |
| 1.3 | **EXEC SQL blocks** — bounded, parseable, semantically unambiguous SQL. | Each block maps 1:1 to a driven-port method. Easy invariant: count(EXEC SQL) == count(port methods). | [ACTIVE] F3 extracts these explicitly |
| 1.4 | **FILE-CONTROL SELECT statements** — file organization (SEQUENTIAL / INDEXED / RELATIVE) and access mode. | Determines the kind of file adapter to generate. | [ACTIVE] F3 captures FD entries |
| 1.5 | **COPY statements** — dependency edges to copybooks. Stable graph. | Resolves the data structures the program operates on. | [ACTIVE] F3 inlines referenced copybooks |
| 1.6 | **PROGRAM-ID + author comments** — naming convention (e.g., `COBTUPDT` = COBol Transaction UPDaTe). | Gives Java package + class naming. | [ACTIVE] F3 extracts; converter persona uses |
| 1.7 | **Inline comments** — author intent. CardDemo's are unusually informative ("Layer: Business logic"). | Treat as informal spec. Cross-check generated code against comment promises. | [TODO] add comment-as-spec validator |
| 1.8 | **Identifier patterns** — `WS-` prefix = working storage, `LK-` = linkage. Conventions encode lifetime. | Maps to Java scope (local vs field vs parameter). | [TODO] add identifier classifier |
| 1.9 | **Call graph** — `PERFORM <paragraph>`, `CALL '<program>'`. Static. | Function/method decomposition is implied. | [TODO] F2 add call-graph extraction |
| 1.10 | **Data-flow within paragraphs** — `MOVE` chains, `COMPUTE` expressions. | Per-paragraph SSA can be derived; tells you intent. | [TODO] symbolic-execution-lite |

## 2. Sibling-file signals (ground truth without runtime)

CardDemo gives us free oracles in adjacent directories. Already wired into F3:

| # | File | What we learn | Status |
|---|---|---|---|
| 2.1 | `dcl/*.dcl` | Exact host variables and their COBOL types. Contract between COBOL and DB2. | [ACTIVE] |
| 2.2 | `ddl/*.ddl` | Table schema, column types, constraints (PK, FK, NOT NULL, CHECK). Hard invariants. | [ACTIVE] |
| 2.3 | `jcl/*.jcl` | Dataset names, file roles (input/output), program invocation order. | [ACTIVE] |
| 2.4 | `bms/*.bms` + `cpy-bms/*.cpy` | Exact screen field layout for CICS. Tells us the UI contract even without running CICS. | [TODO] BMS parser, F3 extension |
| 2.5 | `csd/*.csd` | CICS resource definitions — transaction codes, program names. | [TODO] F3 extension |
| 2.6 | `ctl/*.ctl` | DB2 utility control statements — load/unload data files. | [TODO] F3 extension |
| 2.7 | `README.md` | Natural-language spec. Bullet points under Features/Functions = candidate assertions. | [ACTIVE] F4 extracts |
| 2.8 | `*.proc` (catalogued procedures) | JCL procedure definitions. | [TODO] |

## 3. External knowledge bases (free, public, vendored)

We can read these once and bake their patterns into our prompts/validators.

| # | Source | Purpose | Status |
|---|---|---|---|
| 3.1 | **ANSI/ISO COBOL 85 + COBOL 2014 standards** | Formal semantics. Settles every "what does this statement mean" question. | [TODO] vendor the relevant chapter PDFs to `docs/refs/` |
| 3.2 | **GnuCOBOL test suite** | Hundreds of tiny COBOL programs with documented expected output. Many use the same constructs as CardDemo. | [TODO] add as `corpus/gnucobol-tests/` |
| 3.3 | **NIST COBOL Compiler Validation System (CCVS)** | Conformance tests with formal expected outputs. Same pattern `vb6interpreter-abina` uses for NIST. | [TODO] mirror to `corpus/nist-cobol/` |
| 3.4 | **ProLeap COBOL parser** (Java, OSS) | Battle-tested ANTLR grammar for COBOL 85. Could replace regex-based parsing entirely. | [TODO] evaluate vendoring its grammar |
| 3.5 | **IBM Enterprise COBOL Language Reference** (public PDF) | Authoritative on IBM-extension semantics (COMP-3, packed decimal sign nibble, CICS-COBOL integration). | [TODO] reference, don't vendor |
| 3.6 | **AWS Mainframe Modernization documentation** | Documents the exact COBOL→Java mapping AWS partners (Blu Age, Heirloom) use. Independent reference. | [TODO] cite where relevant |
| 3.7 | **`abhi-ksh/aws-carddemo-modernized`** | Someone's already-modernized CardDemo. Likely incomplete but a real independent reference. | [TODO] read, score, mine for patterns |
| 3.8 | **`Crowdbotics-Research/BENCH-AWS-CardDemo`** | Frontier-model benchmark using CardDemo. May have testcases + scoring. | [TODO] read, may have test vectors |
| 3.9 | **`Frenzy117/aws-carddemo-rag-from-scratch`** | RAG-from-scratch over CardDemo. Different angle on the same data. | [TODO] cross-reference |
| 3.10 | **Academic COBOL semantics papers** (Felleisen et al., legacy-modernization literature) | Formal definitions where the standards leave gaps. | [TODO] cite as needed |

## 4. Reasoning approaches we can apply

When raw signals aren't enough, we apply analysis techniques.

| # | Technique | Determinism it adds | Status |
|---|---|---|---|
| 4.1 | **Static slicing** — given a variable, find all statements that affect it. | Bounds the scope of any single port/use-case. | [TODO] |
| 4.2 | **Control-flow graph (CFG) construction** — paragraphs + PERFORM/GO TO edges. | Detects unreachable paragraphs, ALTER targets, dead code. Surfaces UNCONVERTIBLE-* tags early. | [TODO] |
| 4.3 | **Type inference** — for variables not explicitly typed (rare in COBOL but happens in MOVE chains). | Closes ambiguity gaps in PIC clauses. | [TODO] |
| 4.4 | **Effect analysis** — read/write sets per paragraph. | Identifies which paragraphs are pure, which touch DB/file. Drives port placement. | [TODO] |
| 4.5 | **Symbolic execution (lite)** — execute COBOL with symbolic values, derive path conditions. | Generates test inputs that cover every branch. | [TODO] long-term |
| 4.6 | **AST-level diff** between source COBOL and back-translated COBOL (round-trip). | If we can back-translate the generated Java to COBOL and the diff is small, equivalence is more likely. | [TODO] explore feasibility |

## 5. Cross-source corroboration

When one source gives a probabilistic answer, two sources agreeing make it deterministic-enough.

| # | Method | Status |
|---|---|---|
| 5.1 | **Multi-LLM consensus** — Codex + Claude (+ Gemini optionally) translate the same COBOL. Diff their outputs. If they agree at AST level, high confidence. | [TODO] add `LLM_BACKEND=multi` mode |
| 5.2 | **Triangulation against `abhi-ksh/aws-carddemo-modernized`** — our output and theirs should produce equivalent SQL sequences against identical inputs. | [TODO] once we have output |
| 5.3 | **Differential testing against GnuCOBOL** — for the COBOL subset GnuCOBOL handles (pure COBOL, no CICS/DB2), run the original through GnuCOBOL and the converted through JVM with the same inputs. | [TODO] requires CICS/DB2 stubbing for our CardDemo slice |
| 5.4 | **Comment-as-spec** — author's comments should describe behavior; generated code should plausibly satisfy them. LLM-judge or human review. | [TODO] |
| 5.5 | **Property-based testing** — extract invariants from DDL (FK constraints, NOT NULL) and codify them as JUnit properties in the output. | [TODO] |

## 6. Things COBOL deliberately leaves underspecified

The honest list of "we cannot know this from static analysis alone." These get logged as
`UNCONVERTIBLE-*` or carry a comment flagging the ambiguity.

| # | Ambiguity | Mitigation |
|---|---|---|
| 6.1 | `ALTER` statement — runtime GO TO target rebinding | Out of scope. Tag and skip. |
| 6.2 | Computed GO TO (`GO TO DEPENDING ON`) — control flow indexed by runtime value | Convert to `switch`; flag for review |
| 6.3 | COBOL truncation on `MOVE` to a smaller field | Mirror exactly in Java; add comment |
| 6.4 | Sign handling on packed decimal (COMP-3) — half-byte sign nibble has 6 valid values per standard | Use `BigDecimal`; document edge cases |
| 6.5 | Division by zero behavior — implementation-defined | Convert to explicit guard or `ArithmeticException`; comment |
| 6.6 | `EXEC CICS RETURN` commit semantics — depends on transaction state | Out of step-1 scope (batch only) |
| 6.7 | DB2 isolation level — implicit unless declared | Document chosen default in generated code |
| 6.8 | File-status code interpretation — `'23'` means "record not found" by IBM convention but other vendors differ | Use IBM mapping; document in adapter |
| 6.9 | EBCDIC vs ASCII collation differences | Out of step-1 scope; flag if encountered |
| 6.10 | `OCCURS DEPENDING ON` — variable-length tables | Convert to `List<T>`; the depending-on field becomes the size constraint |

## 7. How we wire each signal into the pipeline

| Phase | Source signals consumed |
|---|---|
| F1 Inventory | 1.1, 1.2, 1.4 (file kinds + complexity scoring) |
| F2 Capture (no runtime) | 2.1–2.8 (documented sources) |
| F3 Context Pack | 1.3, 1.5, 1.6, 2.1, 2.2, 2.3, 2.7 (inlined into the markdown) |
| F4 Golden Master | 2.2 (DDL constraints), 2.3 (JCL DD), 2.7 (README features), 3.7 (independent reference) |
| F5 Convert | All of section 1 + 2, persona-driven |
| F6 Validate | 5.1 (multi-LLM consensus, optional), 5.2 (reference triangulation), 5.4 (comment-as-spec) |
| F7 Inventory update | 6 (mark UNCONVERTIBLE cases for honest reporting in FAILURES.md) |

## 8. The "newABINA spirit" — when a wall appears, find a window

Working principles for adding new signals:

1. **No single source needs to be perfect.** A 60%-reliable signal combined with a 60%-reliable independent signal is ~85% reliable on agreement.
2. **Prefer free signals before paid analysis.** Reading a JCL costs nothing; running CICS costs an AWS account.
3. **Vendor before you build.** ProLeap, GnuCOBOL, NIST — copy what exists, don't redo it.
4. **Honest gaps beat fake completeness.** A documented `UNCONVERTIBLE-*` tag is more valuable than a half-broken silent conversion.
5. **Validate at every layer.** Don't let an LLM call decide alone what's true — corroborate with a parser, a static check, a constraint, a reference impl.
6. **The catalog is the product.** As we add signals, the catalog of "what we know how to handle" grows. That growth IS the prototype's value.

---

## 9. Specialized agents — engineer determinism instead of discovering it

> User insight, 2026-05-20: "instead of assuming it will be deterministic, we try to **build** as much determinism as possible embedded on the pipeline... what can we make agents do, to transform those scripts and translate them more reliable... assuming there is no determinism but we know what we want in a pipeline of coordinated agents."

The inversion: a single big LLM call is unreliable. A swarm of *small* specialists, each with one tiny job, each verifiable independently, gives compound reliability. Their *composition* is the determinism, not any one agent.

### 9.1 Purpose-detection agents (read intent, not just mechanism)

| Agent | Input | Output | Verifiable how |
|---|---|---|---|
| `PurposeAgent` | COBOL + README + JCL + comments | one paragraph: "this program exists to do X for business reason Y" | Cross-check with `IntentConsistencyAgent`; human sanity scan first 3 |
| `ActorAgent` | source + JCL + CSD | who calls this? batch scheduler / CICS user / another program / event? | DD names in JCL ↔ FILE-CONTROL ↔ EXEC CICS RETURN |
| `DomainClassifierAgent` | source + README | domain bucket: ETL, reporting, OLTP, batch maintenance, ... | Closed enum; multi-LLM majority vote |
| `LifecycleAgent` | source | online vs batch vs hybrid; commit boundaries; restart-ability semantics | Static patterns: EXEC CICS RETURN, EXEC SQL COMMIT, COBOL `STOP RUN` |

### 9.2 Behavioral-prediction agents (predict without running)

| Agent | Input | Output | Verifiable how |
|---|---|---|---|
| `EdgeCaseEnumeratorAgent` | source | list of every conditional branch + a sample input exercising each | Compare count to CFG branch count |
| `SymbolicExecutorAgent` | source + input record shape | predicted SQL sequence + output record shape for that input | Run on synthetic inputs; compare to multi-LLM consensus |
| `FailureModeAgent` | source | list of error paths (SQLCA != 0, FILE STATUS != 00, MQ failure) with what the program does in each | Compare against `FAILURES.md` taxonomy |
| `InvariantExtractorAgent` | source + DDL | loop invariants, pre/post conditions, FK invariants | Property-based tests in the generated Java |

### 9.3 Cross-reference agents (corroborate against the world)

| Agent | Input | Output | Verifiable how |
|---|---|---|---|
| `ReferenceCorroboratorAgent` | our slice + URL to abhi-ksh/aws-carddemo-modernized | side-by-side: where we agree on structure with their modernization, where we differ | Diff against their commit |
| `SpecConsistencyAgent` | source + README | flags where README says X but code does Y | Manual review + counter-example |
| `NameSemanticsAgent` | identifiers (program ID, paragraph names) | implied roles; flags mismatches with actual behavior | Closed pattern set (`COBTUPDT` ↔ "COBol Transaction UPDaTe") |

### 9.4 Test-generation agents (produce verifiable artifacts)

| Agent | Input | Output | Verifiable how |
|---|---|---|---|
| `TestVectorAgent` | source + edge cases + symbolic execution | JUnit @Test methods; Java MUST pass these | Tests run against generated Java |
| `PropertyAgent` | DDL + DCL | property-based invariants (jqwik / quickcheck-style) | Generate random inputs, assert invariant holds |
| `GoldenInputAgent` | source + DCL + DDL | realistic sample inputs (records) the program should accept | Diff against DCL types; FK validity check |
| `OracleAgent` | source + reference modernizations (abhi-ksh, AWS docs) | "for input X, expected output is Y" derived from triangulation | Multi-source agreement count |

### 9.5 Translation-quality agents (each polishes one layer)

| Agent | Input | Output | Verifiable how |
|---|---|---|---|
| `ChunkBoundaryAgent` | source + complexity score | recommended chunk boundaries (DIVISION / SECTION / paragraph) | Span limit + 0 cross-chunk references |
| `TypeMappingAgent` | PIC clauses | Java types with confidence + edge-case notes | Closed mapping table; flag overflows |
| `SQLEquivalenceAgent` | one EXEC SQL block + DCL host vars | one Java method that issues equivalent parameterized SQL | Static AST equivalence on SQL after normalization |
| `HexShapeAgent` | rough Java translation | proper layer assignment per method (domain/application/adapter/infra) | ArchUnit rules pass |
| `OTelInstrumentationAgent` | translation | inserts spans + attributes at right boundaries | Coverage scanner: 100% adapter methods have spans |
| `ProvenancePreserverAgent` | source + translation | provenance comments on each Java method with COBOL line range | Regex check |

### 9.6 Refinement agents (loop until green)

| Agent | Input | Output | Verifiable how |
|---|---|---|---|
| `CompileFixerAgent` | translation + `javac` errors | minimal-diff patch | Re-compile passes |
| `HexViolationFixerAgent` | translation + ArchUnit violations | re-layered patch | ArchUnit passes |
| `IdempotenceProverAgent` | translation | output of running translation through converter again | Diff: identical |
| `DriftReducerAgent` | 3 divergent outputs + drift report | tightened prompt/context | Next 3-run drift below threshold |

### 9.7 Adversarial / red-team agents (try to break it)

| Agent | Input | Output | Verifiable how |
|---|---|---|---|
| `AdversarialReviewerAgent` | translation | "given input X (corner case), does Java still match COBOL?" — proposes counter-examples | Run the counter-example; if it breaks, file `T2-*` failure |
| `HallucinationDetectorAgent` | translation | flags any Java method/import without a clear COBOL provenance line | Provenance comment check; LLM review of orphans |

### 9.8 Pipeline shape implied by all of this

```
F1 Inventory
F2 Capture (sibling docs)
F3 Context Pack
  └─ Purpose-detection agents fill metadata header
F4 Golden Master
  ├─ TestVectorAgent
  ├─ PropertyAgent
  ├─ OracleAgent (triangulation)
  └─ EdgeCaseEnumeratorAgent
F5 Convert (multi-stage)
  ├─ ChunkBoundaryAgent → chunks
  ├─ For each chunk:
  │   ├─ TypeMappingAgent (data structures)
  │   ├─ SQLEquivalenceAgent (every EXEC SQL)
  │   ├─ Converter (orchestrator with persona)
  │   ├─ HexShapeAgent (layer assignment)
  │   ├─ OTelInstrumentationAgent (spans)
  │   └─ ProvenancePreserverAgent (comments)
  └─ Reconciler (merge chunks)
F6 Validate
  ├─ T1: invariants checks + CompileFixerAgent loop (max 2) + HexViolationFixerAgent loop (max 2)
  ├─ T2: TestVectorAgent + OracleAgent comparison + AdversarialReviewerAgent counter-examples
  ├─ T3: drift run + DriftReducerAgent
  └─ T4: cost/time metrics from coordinator
F7 Inventory update
F8 Evidence gate
  └─ HallucinationDetectorAgent + provenance audit
```

### 9.9 Cheap vs expensive agents (engineer first the cheap ones)

**Cheap (deterministic, static analysis or closed enums):**
- TypeMappingAgent (mostly a table)
- ChunkBoundaryAgent (parser-driven)
- ProvenancePreserverAgent (regex insertion)
- HallucinationDetectorAgent (provenance regex)
- HexViolationFixerAgent (ArchUnit + patch)
- CompileFixerAgent (javac feedback loop)

These six can be implemented WITHOUT additional LLM calls beyond the converter itself.

**Medium (one LLM call, bounded):**
- PurposeAgent, ActorAgent, LifecycleAgent
- SQLEquivalenceAgent (one block at a time)
- OTelInstrumentationAgent
- IdempotenceProverAgent
- FailureModeAgent
- EdgeCaseEnumeratorAgent

**Expensive (multi-LLM, multi-pass, large context):**
- SymbolicExecutorAgent
- OracleAgent (multi-source triangulation)
- ReferenceCorroboratorAgent (reads abhi-ksh's repo)
- AdversarialReviewerAgent
- TestVectorAgent (generates JUnit)

### 9.10 The compounding effect

If each cheap agent is 90% reliable on its narrow job, and we have 6 of them gating the converter, the chance ALL six agree on a passing result is 0.9^6 ≈ 53%.

But — and this is the point — we only ship when ALL six gates pass. So the **shipped output** is 100% gate-passing. The agents don't make the LLM better; they make us throw away the bad outputs faster, until the LLM produces one that passes all gates.

This is the "engineer determinism into the pipeline" insight: **gates compound to certainty; the LLM is the noisy generator, the gates are the deterministic filter.**

---

## Change log

| Date | Entry |
|---|---|
| 2026-05-20 | Initial catalog created from user's creative brainstorm prompt + my reading of newABINA's Iria method. |
| 2026-05-20 | §9 — specialized-agent architecture added in response to user's second creative brainstorm ("engineer determinism, don't assume it"). |
