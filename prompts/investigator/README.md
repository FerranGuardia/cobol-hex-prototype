# Investigator

Open-ended questioning agent invoked by the convergence loop when the converter plateaus on a slice. **Not a checklist of techniques.** A meta-agent that generates questions, picks one to pursue, attempts it, and logs the result.

## Operating principle

> "When a model tells me 'blocked', I fire them with all this prompts because I may not know but someone probably already did — at least the one who wrote it."
> — user, 2026-05-20

Every COBOL program exists because someone needed it to do something. The author had reasons. The Investigator's job is to **recover that intent** through aggressive questioning, NOT to validate the converter's give-up. A "blocked" verdict from the converter is the START of investigation, not the end.

## Files

```
prompts/investigator/
├── README.md            (this file — philosophy)
├── meta-prompt.md       (the prompt the Investigator agent receives at each invocation)
└── angle-library/       (seed angles — the Investigator can use these, must propose new ones over time)
    ├── 001-author-intent.md
    ├── 002-neighboring-context.md
    ├── 003-language-cousins.md
    ├── 004-middleware-context.md
    ├── 005-corpus-precedent.md
    ├── 006-partial-translation.md
    ├── 007-io-contract.md
    └── (more added by future waves)
```

## How a single invocation works

Input to the Investigator:
- The slice path + source
- The accumulated `acceptance/investigations/<concept>.json` so far
- The full `angle-library/` (read-only)
- The current converter's last failure (violations / error messages / blocker reason)

The Investigator's job in one call:

1. **Read the prior log.** What's already been tried? What angles are exhausted?
2. **Read the angle library.** Are there seed angles not yet attempted on this concept?
3. **Generate 3–5 candidate NEW questions** not already in the prior log. New means: different angle, different reference, different framing. Repeating a question with a synonym is forbidden.
4. **Pick the highest-signal / lowest-cost question.** Bias toward cheap-fast-informative.
5. **Attempt the question.** Read what's needed, run what's needed.
6. **Emit one structured entry** to add to `acceptance/investigations/<concept>.json`:
   ```json
   {
     "wave": N,
     "angle": "human-readable name of the angle",
     "question": "the exact question pursued",
     "sources_consulted": ["paths or URLs"],
     "result": "what we learned",
     "verdict": "candidate-for-converter-retry | partial | exhausted | escalate-to-human",
     "next_idea": "(optional) what to try next if this didn't unblock"
   }
   ```

## What the Investigator must NOT do

- **Propose techniques already in the log.** Each entry must use a distinct angle. Same-angle entries are gate failures.
- **Declare BLOCKED in fewer than 3 wave-distinct entries.** That's a doctrine violation. See `feedback-creative-exhaustion` memory.
- **Limit itself to the seed angle library.** The library is inspiration, not exhaustive. New questions are encouraged and become future seeds.
- **Quote the converter's blocker text as the result.** "Converter couldn't handle EXEC SQL" is not an investigation entry — it's the input.
- **Skip without trying.** If a question is unanswerable from available sources, that itself is a finding worth logging — but the answer is "no source available", not "didn't look."

## Growth path

Every wave that produces a NEW productive angle (one that resulted in a converter retry succeeding) gets that angle's prompt added to `angle-library/`. Numbered sequentially. The library is append-only; never deletes — old angles are kept as reference even when superseded.
