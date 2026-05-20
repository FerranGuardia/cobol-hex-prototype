# FUTURE-IMPROVEMENTS — techniques deferred from step-1

> Deliberately deferred techniques. Each entry documents what it is, why it would help, why it's deferred for step-1, and what would unblock it. **Nothing here is rejected** — everything here is "yes but later."

> Companion to [SPEC.md](../SPEC.md) §Determinism Stack (the in-scope techniques) and [FAILURES.md](../FAILURES.md) (the failure-tag catalog).

---

## D1 — Cross-model differential generation

**What it is.** Run the same slice through two independent LLM providers (e.g. Codex + Claude + Gemini) as parallel third-and-fourth generators alongside the existing code-author / test-author personas. Diff the contracts across models. Cross-model agreement is the single strongest determinism signal in the LLM literature: if the answer is in the *data*, all models converge; if it's in a model's quirks, they don't.

**Why it would help.** It eliminates a class of "shared training-data bias" that K-vote within a single model cannot detect. K=5 runs of Codex can all make the same mistake; one Claude run can break that tie.

**Why deferred.** User stack constraint, 2026-05-20:
> "the third is not a possibility document it but i can't add more constraints to my stack since i only use claude and codex and claude is too expensive to do that, unfeasable"

Claude is the user's *interactive* agent; using it also as a parallel generator on every slice (typically 5+ calls per slice for K-vote × 2 personas) would compound API spend in a way the personal subscription cannot absorb. Codex is the only generation budget available.

**What would unblock it.**
- A second LLM access path with a non-binding budget (enterprise Codex tier, free-tier Gemini, hosted local Llama, etc.)
- Or a usage model where cross-model differential runs only on slices that produce a `T2-CONTRACT-MISMATCH` (failure-triggered, not default-on) — reducing volume to a small minority of slices.

---

## D2 — Symbolic execution / bisimulation between COBOL and Java

**What it is.** Run the COBOL program (via Hercules/MVS 3.8 emulator or GnuCOBOL with stubs for CICS/DB2/MQ) and the generated Java symbolically — both produce labeled transition systems — and prove (or disprove) bisimulation: every state reachable in COBOL has a corresponding reachable state in Java with the same observable behavior. This is the gold-standard equivalence proof in the program-translation literature.

**Why it would help.** Bisimulation is *the* strongest equivalence claim possible short of formal proof. It would replace T2-EQUIVALENCE's reliance on hand-curated `expected-output.txt` with mechanical exhaustive verification.

**Why deferred.**
- Requires a COBOL runtime (Hercules/MVS or GnuCOBOL+stubs). Both are weeks of integration before we get to "first symbolic run."
- Java symbolic execution (JBSE, JPF) does not handle Spring or OTel agents gracefully — would need to strip the infra layer before checking.
- Bisimulation construction on programs with file I/O and SQL requires modeling the external world; the state space explodes quickly.
- The technique is **not necessary for step-1** — hand-curated golden outputs are sufficient at PoC scale.

**What would unblock it.**
- A scale of slices large enough (~100+) that hand-curated oracles become infeasible.
- A user-confirmed need for "formal-grade" equivalence beyond what golden masters provide.
- A tractable subset of the corpus (no CICS, no MQ, deterministic SQL) where the technique can be piloted.

---

## D3 — Metamorphic testing (oracle-free property testing)

**What it is.** Properties of the form "doubling the input doubles the output," "shuffling the input rows doesn't change parsed-record contents," "applying the conversion twice is a no-op." These don't require an oracle — they only require the system under test. Classic technique for legacy translation where ground truth is hard to obtain.

**Why it would help.** Generates many additional test cases at low marginal cost. Catches a class of bugs (off-by-one, ordering, idempotence) that golden-master tests miss because they only check one input.

**Why deferred.**
- Constructing metamorphic relations for COBOL programs requires understanding what properties are preserved — which is itself non-trivial for business logic with conditional branches, fixed-width records, and FILE STATUS handling.
- The technique is most powerful with a COBOL runtime to verify the metamorphic relations on COBOL first (otherwise we're asserting a property on Java without knowing whether COBOL satisfies it).
- Idempotence (#5 in the determinism stack) is a *special case* of metamorphic testing and is already in scope.

**What would unblock it.**
- The same COBOL runtime that unblocks D2.
- A confirmed corpus pattern where metamorphic relations are obvious (e.g. all "tabulate and sum" COBOL programs share "doubling input doubles output").

---

## D4 — Bytecode-level T3 drift detection

**What it is.** Currently T3 (determinism across N runs) is measured at the Java source level: byte-identical or AST-equivalent. Stronger: compile the generated Java deterministically (`javac -g:none -source 21 -target 21` in a hermetic container) and diff `.class` files. Catches a class of "AST-equivalent but compiler-produced different bytecode" cases as well as "tokens-different but bytecode-identical."

**Why deferred.**
- Hermetic container (in scope, Phase B/#8) must land first.
- `.class` files contain a constant pool whose entries are not always emitted in deterministic order; need to normalize before diffing.
- Lower priority than ProLeap AST input (#4), which addresses non-determinism at the *source* level rather than measuring it at the bytecode level.

**What would unblock it.** Hermetic container shipping; an observed case of T3-RUN-DRIFT-SEMANTIC that AST-equivalence missed.

---

## D5 — Token-id-level prompt cache (beyond prompt-hash cache)

**What it is.** Beyond the existing `core/determinism.py` prompt+context+model+seed → SHA-256 cache key, also cache the *token sequence* that the model received and emitted. Allows recovering from cache even when whitespace or comment-formatting changes shifted the prompt hash but the semantic content is identical.

**Why deferred.** Marginal benefit over the existing prompt-hash cache. Codex CLI does not expose tokenization, so we'd have to use a separate tokenizer (`tiktoken` or `transformers`) — which introduces tokenizer-version dependence. Not worth the complexity at step-1 scale.

---

## D6 — Industrialization: oracle generation at scale

**What it is.** The biggest constraint on the methodology generalizing beyond CardDemo is that `corpus/golden-outputs/<slice>.expected-output.txt` is hand-curated. At step-1 scope (14 programs) this is a 10-min-per-slice manual task. At 1,000+ programs it is infeasible.

Three candidate paths:
1. **Use `abhi-ksh/aws-carddemo-modernized` as the oracle** — already-modernized Java code from an external author. Phase 0 of the DIARY's plan-revision was to evaluate this.
2. **Run a COBOL runtime (Hercules/MVS or GnuCOBOL+stubs) to capture actual behavior.** See D2.
3. **Derive expected behavior mechanically from source artifacts** — every JCL DD → a file-presence assertion; every `DISPLAY` statement → a stdout-line assertion with the literal text. Brittle but cheap and infinite.

**Why deferred.** Out-of-scope for step-1's "prove we can do a good translation on CardDemo" goal (see `project-poc-vs-scaling` memory). Industrialization is the post-PoC phase.

**What would unblock it.** PoC concept-proven on CardDemo; commitment to scale beyond the 14 step-1 slices.

---

## How to add an entry

When a technique is brought up and deferred (rather than rejected), add an entry here following this template:

```markdown
## DN — Short technique name

**What it is.** 1-3 sentences describing the technique.
**Why it would help.** What failure mode or limitation it addresses.
**Why deferred.** Concrete reason — user stack, scope, dependency on something not yet built, etc.
**What would unblock it.** Specific condition(s) under which we'd revisit.
```

This file is append-only; never delete a deferred technique. Mark `RESOLVED — moved into scope in <wave>` if and when an entry is promoted into the active design.
