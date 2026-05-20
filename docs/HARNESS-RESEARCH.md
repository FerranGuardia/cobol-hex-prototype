# HARNESS-RESEARCH — what we learned from vfp9, newABINA, vb6 before designing ours

Date: 2026-05-20. Source repos surveyed (paths absolute):

- `/Users/ferranguardiapuig/repos/vfp9interpreter` (branch `main`, 526 commits ahead of origin) — the most mature
- `/Users/ferranguardiapuig/repos/newABINA` (branch `fronta-limpio`) — the QA-consolidation branch
- `/Users/ferranguardiapuig/repos/vb6interpreter-abina` (branch `codex-abina`)

The three were surveyed independently. This document is the cross-cutting synthesis.

---

## 1. Cross-cutting patterns (the things all three repos converged on)

| # | Pattern | Repos | Where it lives |
|---|---|---|---|
| 1.1 | **Single-entry hard gate** — one command runs everything; every step is binary pass/fail; no soft steps | vfp9, vb6 | `scripts/gate.js` (vb6 has 30 steps); vfp9 has `./diff.sh --only-passing` + `./diff.sh --bugs B<NN>` |
| 1.2 | **Classified external corpora (VALID / NEGATIVE / OUT-OF-SCOPE)** — every input is explicitly tagged; the gate enforces parser must accept VALID and reject NEGATIVE | vb6, vfp9 | `vb6: scripts/check-classified-corpus.js`; `corpus/external/*/CLASSIFICATION.md` |
| 1.3 | **Acceptance matrix + capabilities matrix split** — separate "what we proved" from "what we claim to support". Each tied to a gate step. | vb6 (formal), vfp9 (implicit) | `tasks/acceptance-matrix.json` + `tasks/capabilities.json`; 7-item rule (normative source + empirical source + comparative source + own fixture + classification + hard check + decision date) |
| 1.4 | **Round-trip property test for AST fidelity** — parse → print → reparse → assert AST equality (ignoring positions) | vb6 | `scripts/round-trip.js` clusters failures into `parseFail / printFail / reparseFail / astMismatch` |
| 1.5 | **Architecture guard (programmatic layer enforcement)** | newABINA, vb6 | `newABINA: ArchitectureTest.java` (11 ArchUnit rules: domain has zero Spring/JPA/Jackson; dependency direction enforced); `vb6: scripts/check-architecture.js` (catch-all bloat blocked at 1,300 LOC) |
| 1.6 | **NIST-anchored conformance suite with metadata headers** — every test file carries `@id`, `@section`, `@grammar`, `@rule`, `@assertion` linking it to the spec | vb6 | `nist/tests/{lex,lit,op,stmt,proc,arr,err,builtin}/*.bas` + `nist/runner.js`; reports as `nist/reports/latest.json` |
| 1.7 | **Per-task evidence capture** — every fix has `pre.log / post.log / regression.log` snapshot | vfp9 | `tasks/_done/bugfix-w1/evidence/task<NN>/` |
| 1.8 | **Pre-commit forbidden without gate green** — hard rule: agent cannot `git commit` until the bug's gate step is green | vfp9 | `AGENT.md:42-50` — "PROHIBIDO git commit sin diff.sh --bugs B<NN> verde" |
| 1.9 | **No-npm supply-chain hygiene** — never invoke `npm install` in the call chain; pre-install once, verify hashes, use local `node_modules/.bin/<tool>` directly | vb6 | ADR 0002; post-May-2026 Shai-Hulud npm campaign response |
| 1.10 | **QA session log format** — rolling `docs/qa/YYYY-MM-DD_session.md` with `symptom / reproduce / root-cause / evidence / status` per bug | newABINA | `docs/frontal/qa/2026-05-18_qa_session.md` — 700 lines, 8 bugs cataloged with root causes |
| 1.11 | **Deferred bugs go to next wave, never silently reopened** — once a bug is marked `DEFERRED wave-N+1`, no commit may "fix it on the side" | vfp9 | `AGENT.md:15-16` — B08 deferred because it uncovered a cascade |
| 1.12 | **No-shadow rule** — only one source of truth per concern; plans/docs are narration, the matrix is state | vb6 | `docs/acceptance.md:63-69` |
| 1.13 | **Surgical fixes only — "fix minimal, don't refactor"** — no "while we're here" changes; one logical fix per commit | vfp9, newABINA | `vfp9: achievements/2026-05-14-cnvalbpro.md` "fix minimal, don't refactor"; `newABINA: CLAUDE.md` hard rule |
| 1.14 | **No-stubs hard rule** — empty handlers, `throw new UnsupportedOperationException`, `() => {}` placeholders all banned by automated check | newABINA | hard rule #4 (added after Stock Disponible dialog shipped as stub) |
| 1.15 | **Determinism via fixed environment contracts** — no `process.cwd()`, no ambient paths, four-root contract for legacy code | vfp9 | `CLAUDE.md:193-214`; checked via `// ALLOW-CWD` comment scan |

## 2. Problems each repo encountered (so we don't repeat them)

These are *retrospective findings* from each project — things they tried and walked back. Worth more than the success patterns.

### From vfp9

- **Float equality is too strict.** Had to fall back to tolerance comparison (IEEE 754 rounding eats exact equality). Implication for us: token counts and timing are *bounded ranges*, not exact targets.
- **Tests sharing one DB must be serial.** `wgdemo.db` couldn't be parallelized; concurrent tests corrupted state. Implication: our run cache must be per-run (it is) and harness execution must be serial.
- **"While we're here" is a trap.** Mixing unrelated fixes in one commit → multiple regressions. Hard rule added: one bug, one commit.
- **Some specs are irreducible.** Files in the corpus that can't parse without new grammar — separate concern from current bugfix track; documented as parse-failures-irreducible.html so they aren't forgotten or reopened mid-task.
- **B08 cascade.** A single bug uncovered five downstream failures. Lesson: bugs that surface cascades MUST be deferred to a dedicated wave with explicit scope.
- **VFP9.exe golden divergences.** Sometimes the reference itself was wrong. They built an escalations-to-foxnist.md track so disputed cases unblock current work.

### From newABINA

- **Eager auto-fetching broke VB6 parity.** "Helpful" optimization (preload dropdowns) drifted behavior. Walked back to event-driven loading. Lesson for us: do not let the converter add "helpful" Java patterns that aren't in the COBOL — `T1-OVER-HELPFULNESS` failure tag is a real risk.
- **Stub components shipped silently.** `StockAvailabilityDialog` was a placeholder forever. Hard rule "no stubs" added. We already have this in `SPEC.md` (no `UnsupportedOperationException`, no `// TODO`); we should add a gate step that scans for it.
- **Context packs originally lacked control metadata.** SQL alone wasn't enough — UPL control tree was missing. Lesson: our context pack should include EVERYTHING semantically relevant, not just the obvious files. We currently include COBOL + DCL + DDL + JCL + README. Likely we'll discover we also need: copybook closure (we do that), MAP definitions (BMS for CICS, not relevant in wave 1), CSD (CICS resource definitions, not relevant in wave 1).
- **State-mutation routing must be explicit.** Implicit parent-child state sharing caused bugs (`Activar Pdte. Desp.`). They moved to explicit `UseCase + Port + Adapter` for every mutation. For us: every COBOL `MOVE` to a database field must produce a use-case method, not a direct adapter call.
- **Audit must precede translation.** 11 gaps in Fabricación Kits were caught by post-audit, not E2E tests. Implication: F1 inventory should be richer than a file listing — it should be an audit checklist per program.

### From vb6

- **Original parser was over-permissive.** Negation corpus (gap B closure, 2026-05-13) added because parser silently accepted invalid VB6. **For us:** we need a `negative-corpus/` of deliberately-broken inputs the pipeline MUST reject with clear errors.
- **npm CLI removal.** May 2026 Mini Shai-Hulud supply-chain attack → policy: never invoke `npm install` in the call chain; pre-install once, verify hashes. We're Python-based, but the equivalent: pin requirements with hashes (`pip install --require-hashes`).
- **Grammar regeneration must be explicit.** Used to happen lazily, caused stale-parser bugs. Now `check-parser` step paranoia-checks parser.js is newer than grammar.pegjs. For us: prompts are like grammar — when `prompts/converter.md` changes, all prior runs cached against the old prompt should be invalidated. Currently the cache key includes prompt content (good); we should also commit prompt SHAs into `acceptance/matrix.json` so we can correlate.

## 3. Applicability scorecard for cobol-hex-prototype

| Pattern from research | Direct applicability | Priority for us | Notes |
|---|---|---|---|
| Single-entry hard gate (`harness/gate.py`) | ★★★★★ | **Build now** | The user's explicit ask; recycles vb6's `scripts/gate.js` shape |
| Classified corpora (VALID/NEGATIVE/OUT-OF-SCOPE) | ★★★★★ | **Build now** | Extend `docs/CANDIDATES.md` to formal classification; add `corpus/negative/` |
| Acceptance + capabilities matrix split | ★★★★☆ | Build wave-2 | We have `acceptance/matrix.json` placeholder; need the 7-item rule + capabilities lanes |
| Round-trip property test | ★★★☆☆ | Build wave-2 | Convert → reverse-convert → diff. Higher value as the converter matures. |
| ArchUnit programmatic layer enforcement | ★★★★★ | **Build now** | Replaces our naive regex T1; mirrors newABINA's 11 rules |
| NIST-anchored conformance | ★★★★☆ | Build wave-3+ | The COBOL equivalent exists (NIST CCVS); vendor a subset later |
| Per-task evidence capture | ★★★★☆ | Build wave-2 | Our `artifacts/<run-id>/` already does this informally; needs structuring |
| Pre-commit forbidden without gate green | ★★★☆☆ | Build wave-2 | git hook; trivial once gate exists |
| No-npm hygiene (= pip hash pinning) | ★★★☆☆ | Build wave-2 | `pip install --require-hashes` once we lock deps |
| QA session log format | ★★★☆☆ | Build wave-2 | Add a template under `docs/qa/`; first entry the day we hit our first real bug |
| Deferred bugs go to next wave | ★★★★☆ | Build wave-1 | Add to FAILURES.md schema: every UNCONVERTIBLE-* has a target wave |
| No-shadow rule | ★★★★☆ | Build wave-1 | `acceptance/matrix.json` is the only state; everything else is narration |
| Surgical fixes only | ★★★★★ | **Doctrine now** | Add to AGENTS.md when we have one |
| No-stubs hard rule | ★★★★★ | **Build now** | Gate step that lexically rejects `UnsupportedOperationException`, `// TODO`, `() => {}`, empty methods |
| Fixed environment contracts | ★★★☆☆ | Build wave-2 | Replace `process.cwd()` with config-driven paths |

## 3.5. Deliberate divergence from the research: NO `OUT-OF-SCOPE` classification

The research showed all three reference projects use `OUT-OF-SCOPE` as a day-1 corpus classification (vb6 uses it for `.frm` designer files; vfp9 uses it for features the runtime doesn't execute). **We do not copy this pattern.** Per user direction (saved as `feedback-creative-exhaustion` memory):

> "I don't like OUT-OF-SCOPE in a tool like that... needs an input and an output and maybe communicate what it can't but if it can't needs to be justified by at least a wave of research and 3 iterations creatively."

A tool whose stated purpose is to do COBOL→Java conversion does not get to label inputs OUT-OF-SCOPE before attempting them. Instead we use:

- **VALID** — converts successfully
- **NEGATIVE** — deliberately invalid input, MUST be rejected with diagnostic
- **INVESTIGATING** — actively being worked on by the convergence loop + Investigator agent
- **BLOCKED** — terminal state, requires ≥3 wave-distinct entries in `acceptance/investigations/<concept>.json` proving creative exhaustion. The harness gates this — a BLOCKED tag without an evidence log fails the gate.

This is the project's first explicit divergence from the recycled patterns. See `HARNESS-DESIGN.md` increment 2 + 5 for how it manifests.

## 4. Things we deliberately won't copy

- **Frida hooks / runtime capture.** We don't run COBOL; legacy runtime is out of scope (see `project-scope-clarification` memory).
- **Multi-DB adapter matrix.** Single target stack (Java + Spring Boot) for now.
- **VB6 .frm designer header parsing.** No COBOL form designer equivalent at our scope.
- **Modal helper pattern.** No interactive UI on our side.
- **Property Get/Let semantics**, **debugger frontend**, **OLE/COM shims**, **ABINA-specific SDIC integration** — all VB6-or-newABINA-specific, not transferable.
- **Multi-LLM ensembling, Codex+Claude+Gemini majority vote.** Not in step 1; only Codex.

## 5. Failures-mode insights gained from research (to add to FAILURES.md)

New tags we should pre-create in `FAILURES.md` based on what other projects observed:

| Tag | Source project | Trigger condition for us |
|---|---|---|
| `T1-OVER-HELPFULNESS` | newABINA (eager loading) | Generated Java adds features not in the COBOL (e.g., adds caching, fetches eagerly, adds null checks where COBOL would crash) |
| `T1-STATE-MUTATION-IMPLICIT` | newABINA (Activar Pdte Desp.) | Generated code mutates via parent-child sharing rather than explicit use-case-via-port |
| `T1-PARSER-OVER-PERMISSIVE` | vb6 (gap B) | Pipeline accepts a COBOL file it should refuse to convert (e.g., contains `ALTER` but no UNCONVERTIBLE-ALTER tag emitted) |
| `T1-CASCADE-RISK` | vfp9 (B08) | A single fix produces multiple regressions; flag for wave deferral |
| `T2-FLOAT-EXACT-EQUALITY` | vfp9 | T2 uses exact equality where tolerance is appropriate |
| `T3-DB-SHARED-CORRUPTION` | vfp9 (wgdemo.db) | Parallel runs corrupt shared state; serial-only enforcement |

## 6. Single biggest lesson from doing this research

The harness is not five layers stacked once. **The harness is a *culture* — surgical commits, classified corpora, single source of truth, deferred bugs that never silently reopen.** All three repos converged on this culture independently. Building gate.py without the culture would be cargo-culting.

So we don't ship "the harness" as a one-shot artifact. We ship:

1. **The gate** (harness/gate.py — single command, hard steps)
2. **The culture** (AGENTS.md / CLAUDE.md hard rules — surgical commits, no stubs, deferred bugs)
3. **The matrix** (acceptance/matrix.json — only board)
4. **The corpora classification** (VALID / NEGATIVE / OUT-OF-SCOPE in CANDIDATES.md)
5. **The evidence trail** (per-run artifact directory + QA session log)

In that order. Each builds on the previous.
