# HARNESS-DESIGN — what we'll build, in what order

> Proposed design grounded in [HARNESS-RESEARCH.md](HARNESS-RESEARCH.md). Phase A (contract validation + K-vote + mechanical extraction + drift checks + idempotence + reverse-translate) **landed 2026-05-20 session-2** under `src/harness/`. Lower sections of this doc reflect the original increment plan and are partially superseded by what shipped.

The research said the harness is a culture, not a one-shot artifact (research §6). The original plan had five increments. Phase A in session-2 collapsed increments 1, 3, 4, and 5 into a single landing focused on the wave-2 drift catches.

## Current shape (session-2, Phase A landed)

`harness/` was moved from the repo root to `src/harness/` so setuptools' `find` (under `src/`) discovers it. The package is imported as `harness` directly (no `src.` prefix).

```
src/harness/
├── __init__.py
├── contract/
│   ├── validate.py    # JSON Schema + canonical-form check + retry-prompt builder
│   ├── diff.py        # semantic diff between code-author and test-author contracts
│   └── kvote.py       # K-vote field-by-field majority across N contracts
├── extract/
│   └── cobol_facts.py # mechanical extractor: EXEC SQL, FILE STATUS, paragraphs, COPY, SELECT, CEE3xxx, DISPLAY
├── checks/
│   ├── drift_checks.py     # the 5 wave-2 drift catches (file-org, abend-catchable, path-leak, charset, duplicated-output)
│   ├── idempotence.py      # second-pass diff: code-author on own output should be no-op
│   └── reverse_translate.py # structural diff between original COBOL and reverse-translated COBOL
└── rules/               # placeholder for semgrep rules (Phase D, deferred)
```

### Still to land (Phase B/C/D)
- ProLeap COBOL AST integration (Phase C)
- Hermetic JDK/Maven/ProLeap container (Phase B)
- Semgrep rules + compile gate (Phase D — superseded by Maven test-author output)
- Two-pass F5 orchestrator wiring (replaces the current single-pass `convert.py`)
- Curated `corpus/golden-outputs/CBACT02C.expected-output.txt`

---

## Original 5-increment plan (kept for reference)

---

## Increment 1 — The gate skeleton + no-stubs + provenance + hex-shape (THIS WAVE)

**Goal:** replace the naive T1 regex check with a real `harness/gate.py` that runs a sequence of HARD checks. No semgrep, no LLM, no compile yet — just deterministic static checks on the generated Java tree.

```
harness/
├── __init__.py
├── gate.py             # single entry; runs all layers in order; returns structured JSON
└── checks/
    ├── __init__.py
    ├── shape.py        # hex layout (file paths match /(domain|application|adapter|infra)/)
    ├── stubs.py        # no UnsupportedOperationException, no // TODO, no empty methods
    ├── provenance.py   # every file has /* Generated from ... */ header; line ranges parsable
    ├── domain_purity.py # domain/ files have no imports from io.opentelemetry / org.springframework / jakarta.persistence
    └── otel_presence.py # every usecase method opens a spanBuilder; every adapter method same
```

Each check returns:
```python
@dataclass
class CheckResult:
    name: str
    status: Literal["pass", "fail"]
    violations: list[Violation]  # file path + line + message + failure_tag
```

`gate.run(output_dir)` runs every check, accumulates violations, returns a `GateReport`. Wired into the F6 validator: `T1.status = "pass" iff every check passes`.

**Recycle from research:**
- vb6: gate.js sequential-with-fail-fast model (§1.1)
- newABINA: ArchUnit-style layer enforcement (§1.5)
- newABINA: no-stubs hard rule (§2 / FAILURES-mode `T1-OVER-HELPFULNESS`)

**Won't ship in increment 1:** semgrep rules, mvn compile, multi-LLM consensus, drift detection. Those are increment 3+.

**Acceptance:** running `harness.gate.run()` on the wave-1 CBACT02C output we already have should still pass (the output already satisfies these invariants — we observed this manually in the wave-1 readout). If it doesn't, we found a real T1 bug to file.

## Increment 2 — Doctrine + matrix + corpora classification

**Goal:** establish the *culture* so building further increments doesn't drift. No code; only docs and JSON.

```
AGENTS.md                # operating doctrine: surgical commits, no stubs, deferred bugs, source-of-truth hierarchy
acceptance/
├── matrix.json          # the only state board; entries follow the 7-item rule from vb6 §1.3
└── investigations/      # per-concept investigation logs (see "BLOCKED is earned")
corpus/
└── classification.json  # per-program: VALID | NEGATIVE | INVESTIGATING | BLOCKED
                         # NOTE: no OUT-OF-SCOPE. See feedback-creative-exhaustion memory.
```

**Critical divergence from vb6 / vfp9:** we do NOT use `OUT-OF-SCOPE` as a corpus classification. The user's hard rule (`feedback-creative-exhaustion`):
> A tool that puts an OUT-OF-SCOPE sticker on day 1 is a tool that makes excuses. BLOCKED is a terminal state earned through ≥3 wave-distinct investigation attempts.

So our classification states are:
- **VALID** — the pipeline converts it successfully.
- **NEGATIVE** — deliberately invalid input the pipeline MUST reject with a diagnostic.
- **INVESTIGATING** — actively being worked on; the Investigator agent (increment 5) is proposing new angles each wave.
- **BLOCKED** — terminal, but only after `acceptance/investigations/<concept>.json` has ≥3 distinct approach entries demonstrating creative exhaustion. The harness gates this — a `BLOCKED` entry without an evidence log is itself a gate failure.

`AGENTS.md` ports the hard rules verbatim from newABINA's CLAUDE.md + vfp9's bugfix-w1/AGENT.md, COBOL-adapted:

1. PROHIBIDO `git commit` while T1 is red on a touched file.
2. One bug, one commit (no mixed fixes).
3. No stubs in generated code. Ever.
4. No "while we're here" refactoring during a fix.
5. Deferred bugs go in FAILURES.md with a target wave; never silently reopened.
6. acceptance/matrix.json is the only board. Plans + diary are narration.
7. Source-of-truth hierarchy: COBOL source > JCL > DCL/DDL > README > SPEC.md.

**Recycle from research:**
- vfp9 AGENT.md hard rules (§1.8, §1.11, §1.13)
- vb6 no-shadow rule + 7-item acceptance rule (§1.3, §1.12)
- newABINA hard rules + source-of-truth hierarchy (§1.10, §1.14)

**Won't ship:** the actual git hook (that's increment 5).

**Acceptance:** opening these files and reading them top-to-bottom is the acceptance. The matrix.json schema validates with `jsonschema`.

## Increment 3 — Semgrep rules + javac compile gate

**Goal:** elevate the static checks from regex/AST-in-Python to industry-standard tools. Adds the compile gate (T1's hardest property).

```
harness/
├── rules/                       # semgrep rules (loaded by gate.py)
│   ├── domain_purity.yml
│   ├── usecase_otel.yml
│   ├── adapter_otel.yml
│   ├── naming.yml
│   └── no_stubs.yml             # stronger than the Python regex version
├── compile.py                   # generates a minimal pom.xml if absent, runs `mvn compile`
└── checks/...                   # existing checks now call semgrep instead of native Python
```

Semgrep gives us:
- proper Java AST awareness (vs string regex)
- rule-as-data (mentor can read/edit `.yml` without touching Python)
- standard CI integration when we get to that

The compile gate is the ultimate T1 test. If `javac` rejects it, the generated code is broken regardless of what passed before.

**Recycle from research:**
- vb6 round-trip property test (we adapt: parse Java with javalang, scan with semgrep, both should agree) (§1.4)
- newABINA dual-profile (h2/sqlserver) — equivalent in our world: scan with both semgrep AND javalang as cross-check (§1.5)

**Won't ship:** semgrep CI integration (manual invocation only at this stage).

**Acceptance:** semgrep rules running on the wave-1 output produce 0 violations (the output is genuinely clean). mvn compile against generated pom passes.

## Increment 4 — Structural auditor + provenance coverage

**Goal:** assert that the generated code is *complete* — every COBOL feature has a representation in the Java tree. Closes the "we converted half the program and the validator didn't notice" risk.

```
harness/
├── audit/
│   ├── copy_resolution.py       # every COPY in source has a domain model in output
│   ├── jcl_binding.py           # every JCL DD has an adapter wired
│   ├── exec_sql_mapping.py      # every EXEC SQL block has a port method (wave 4+)
│   ├── port_implementation.py   # every port has ≥1 adapter; every adapter implements all methods
│   └── coverage.py              # union of provenance line ranges covers ≥95% of PROCEDURE DIVISION
```

The COBOL → Java mapping is *recoverable* because we have provenance comments. Parse them, build a graph, assert completeness.

**Recycle from research:**
- newABINA `gm-buscador-articulos.spec.ts` golden-master with hard-coded expected arrays (§1.10) — equivalent: hard-coded "the JCL says DD CARDFILE; the adapter must accept Path arg named cardFilePath or equivalent"
- vfp9 corpus comparison (§1.1) — equivalent: every COBOL paragraph maps to a Java method (line ranges checked)

**Won't ship:** the negative-test side (deliberately broken Java should be rejected) until we have a corpus of generated outputs to test against.

**Acceptance:** the auditor runs on wave-1 output and produces a coverage report showing >95% of CBACT02C lines have a provenance reference.

## Increment 5 — Convergence loop + Investigator agent + git hook + classification gate

**Goal:** when the harness fails, the converter is re-invoked with the violations as input. Bounded retries. **Crucially:** before a slice gets marked `BLOCKED`, an Investigator agent proposes a NEW creative angle. The git hook prevents committing while red.

```
harness/
├── loop.py              # the convergence orchestrator (see lifecycle below)
├── investigator.py      # the Investigator agent — proposes alternate angles when retries plateau
├── classification.py    # gate enforces: every file in classification.json has its expected status
└── investigations/      # per-concept investigation logs (acceptance/investigations/<concept>.json)

.git/hooks/
└── pre-commit           # runs `harness.gate.run()` on currently-generated artifacts; blocks if red
```

### Convergence loop lifecycle (per slice)

```
attempt 1: converter naive
          ↓ T1 red?
attempt 2: converter + violations from attempt 1 in prompt (vfp9 pattern)
          ↓ T1 still red?
attempt 3: converter + accumulated violations
          ↓ T1 STILL red?
─────────── plateau detected ────────────
Investigator agent runs:
  - reads source from a *different* angle (e.g., focus on data flow not control flow)
  - consults a *different* reference (e.g., NIST CCVS for similar idiom; abhi-ksh/aws-carddemo-modernized for a comparable case)
  - proposes a *new technique* not yet tried (e.g., "treat this paragraph as a state machine, not procedural")
  - emits an `investigation_entry` for acceptance/investigations/<concept>.json
attempt 4: converter + Investigator's new angle
          ↓ T1 still red?
Investigator runs again with the new constraint of "do not propose anything already in the log"
attempt 5: converter + second new angle
          ↓
... continues until investigation log has ≥3 distinct attempts AND last 2 are exhausted
final state: BLOCKED-<concept>-AFTER-N-WAVES, with full investigation log
```

**No file gets `BLOCKED` without ≥3 wave-distinct investigation entries.** The gate enforces this; emitting `BLOCKED` with an empty or short investigation log fails the gate itself.

### Convergence rules

- max 3 plain-LLM retries per file (vfp9 surgical fix discipline)
- max 3 Investigator-driven retries (each must propose a new angle)
- max 5 methodology iterations per slice across all of the above (anti-infinite-loop ceiling)
- ≤10% BLOCKED rate before we call the methodology stable
- **Every BLOCKED has investigation evidence** — see `feedback-creative-exhaustion` memory + `FAILURES.md` "BLOCKED is earned" section

### Recycle from research:
- vfp9 PROHIBIDO git commit (§1.8)
- vb6 supply-chain hygiene equivalents (§1.9) — adapt to Python `pip install --require-hashes`
- **Divergence from vb6/vfp9:** they treat unsupported features as OUT-OF-SCOPE on day 1. We don't. Every BLOCKED is earned (see `feedback-creative-exhaustion`).

**Won't ship:** automated escalation to a wave-2 issue tracker (that's a wave-3 concern).

**Acceptance:** running the convergence loop on a *deliberately broken* wave-1 output (we inject a hex-violation manually) — detects, re-prompts, eventually fixes OR produces a populated investigation log + BLOCKED tag. The gate refuses to accept BLOCKED tags lacking the log.

---

## Ordering rationale

| Increment | Why it goes first | Blocks what? |
|---|---|---|
| 1 — gate skeleton | We can verify the wave-1 output programmatically (currently we eyeball) | Increment 5 needs the gate to exist before re-invoking the converter |
| 2 — doctrine + matrix | No code dependency; pure cultural foundation that protects increments 3–5 from drift | Increment 3 (semgrep rules) is meaningless without `acceptance/matrix.json` to bind them to |
| 3 — semgrep + compile | Upgrades the static checks; needs the gate (1) and the matrix (2) | Increment 4 (auditor) reuses the AST infrastructure semgrep installs |
| 4 — structural auditor | Catches "incomplete conversion" which static checks can't see | Increment 5's convergence loop is more useful when the auditor is informing it |
| 5 — convergence loop + git hook | Operationalizes the whole stack as a re-invocation cycle | Nothing — this is the final increment |

## What we are *deliberately not* doing in any increment

- **Running the original COBOL.** Out of scope (`project-scope-clarification` memory).
- **Multi-LLM ensembling.** Codex only; we may add others later.
- **Vendoring NIST CCVS subset.** Wave-3+ — too much upfront effort for unclear gain when CBACT02C-class slices already pass T1.
- **W3C traceparent SQL-to-request correlation.** Wave-4+ — only relevant once we have generated code running with SQL.
- **A web portal / pipeline UI.** Last priority. Maybe never.

---

## The single open question for you

Increment 1 is small enough to ship in this conversation. Increments 2–5 are each meaningful work that can be deferred without breaking what's already shipped. Do you want me to:

**(a)** Build all five increments now, in one push? (Bigger commit, less iteration, risk of drift.)
**(b)** Build increment 1 only, validate it against the wave-1 artifacts, then come back for 2 with what we learned? (Smaller commits, slower, more honest.)

My read: **(b)** is more aligned with the surgical-fix doctrine we just researched. But it's your call.
