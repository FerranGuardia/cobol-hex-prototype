"""F5 — two-pass orchestrator (code-author ‖ test-author).

Drives the central rigor step of the pipeline:

1. Build the context pack (caller's job — F3).
2. Call **code-author** persona K times (parallel), each with validate-and-retry
   up to 3 attempts. Take K-vote majority on the contracts.
3. Call **test-author** persona K times (parallel), each with validate-and-retry.
   Take K-vote majority.
4. Diff the two majority contracts (`harness/contract/diff`). Any `critical`
   entries = `T2-CONTRACT-MISMATCH`, surfaced to the Investigator.

Modes:
- `two-pass-blind` (default): both personas, blind to each other. Maximal-rigor.
- `single-pass`: code-author only. Legacy wave-1/2 behavior. Kept for regression.

K parameter:
- K=1 (default): one call per persona. Cheap. Validate-and-retry still runs.
- K>=3: K-vote on field-by-field majority. Each call uses `force=True` to bypass
  the prompt-hash cache (the cache key is identical across K calls; force=True
  guarantees each call is a fresh Codex invocation that may exhibit run-to-run
  noise even at temp=0).

Parallelism:
- Within a persona, K calls run in parallel via ThreadPoolExecutor (Codex calls
  are subprocess.run, GIL-friendly).
- Across personas, code-author and test-author run in parallel.
- Worst-case wall-clock: max(code-author K parallel, test-author K parallel) ≈
  ~5–10 min per slice regardless of K (subject to subprocess concurrency limits).

Artifacts written:
- `output/com/example/cobol/<slice>/**/*.java`         (from code-author)
- `output/com/example/cobol/<slice>/src/test/**/*`     (from test-author)
- `output/com/example/cobol/<slice>/pom.xml`           (from test-author)
- `contracts/public-contract.code-author.json`         (K-vote majority)
- `contracts/public-contract.test-author.json`         (K-vote majority)
- `contracts/diff.json`                                (semantic diff)
- `raw/code-author/response-<i>.json`                  (per-K raw responses)
- `raw/test-author/response-<i>.json`                  (per-K raw responses)
- `codex_response.json`                                (backwards-compat: code-author run 0)
"""
from __future__ import annotations

import concurrent.futures
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.coordinator import Coordinator
from app.core.schemas import RunConfig

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
CODE_AUTHOR_PROMPT = PROMPTS_DIR / "code-author.md"
TEST_AUTHOR_PROMPT = PROMPTS_DIR / "test-author.md"

PERSONA_PROMPT: dict[str, Path] = {
    "code-author": CODE_AUTHOR_PROMPT,
    "test-author": TEST_AUTHOR_PROMPT,
}

JAVA_BLOCK = re.compile(
    r"```java\s+//\s*(?P<path>[^\n]+)\n(?P<body>.*?)```",
    re.DOTALL,
)
XML_BLOCK = re.compile(
    r"```xml\s+//\s*(?P<path>[^\n]+)\n(?P<body>.*?)```",
    re.DOTALL,
)
TEXT_BLOCK = re.compile(
    r"```text\s+//\s*(?P<path>[^\n]+)\n(?P<body>.*?)```",
    re.DOTALL,
)
JSON_CONTRACT_BLOCK = re.compile(
    r"```json\s+//\s*(?P<path>contracts/[^\n]+)\n(?P<body>.*?)```",
    re.DOTALL,
)

MAX_VALIDATE_RETRIES = 3
Mode = Literal["two-pass-blind", "single-pass"]


@dataclass
class PersonaResult:
    persona: str
    k: int
    contracts: list[dict[str, Any]]
    files: list[dict[str, str]]   # per-K {relpath: body} for emitted files (Java/XML/text)
    raw_responses: list[dict[str, Any]]
    majority_contract: dict[str, Any]
    field_agreement: dict[str, float]   # K-vote per-field agreement; empty for K=1
    divergent_fields: list[str]
    contract_valid: list[bool]          # final-attempt validity per-K
    chosen_files_index: int             # which K-run's files we ship (default 0)

    def summary(self) -> dict[str, Any]:
        return {
            "persona": self.persona,
            "k": self.k,
            "files_emitted": len(self.files[self.chosen_files_index]) if self.files else 0,
            "contract_valid_count": sum(1 for v in self.contract_valid if v),
            "divergent_fields_count": len(self.divergent_fields),
            "chosen_run_index": self.chosen_files_index,
        }


def run(
    cfg: RunConfig,
    run_id: str,
    source_file: Path,
    *,
    force: bool = False,
    k: int = 1,
    mode: Mode = "two-pass-blind",
) -> Path:
    """F5 entry. Returns the output dir."""
    coord = Coordinator(cfg)
    context_pack_path = cfg.artifacts_dir / run_id / "context_pack.md"
    if not context_pack_path.exists():
        raise FileNotFoundError(
            f"context_pack.md missing; run `app context-pack --file {source_file}` first"
        )
    context = context_pack_path.read_text()
    artifacts_root = cfg.artifacts_dir / run_id

    if mode == "single-pass":
        code_result = _run_persona(coord, "code-author", context, k=1, force=force)
        _save_persona(artifacts_root, code_result)
        _save_backcompat_codex_response(artifacts_root, code_result)
        return artifacts_root / "output"

    # Two-pass blind: run both personas in parallel; each persona may further
    # parallelize K calls internally.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f_code = pool.submit(_run_persona, coord, "code-author", context, k=k, force=force)
        f_test = pool.submit(_run_persona, coord, "test-author", context, k=k, force=force)
        code_result = f_code.result()
        test_result = f_test.result()

    _save_persona(artifacts_root, code_result)
    _save_persona(artifacts_root, test_result)
    _save_backcompat_codex_response(artifacts_root, code_result)

    # Contract diff
    from harness.contract.diff import diff_contracts
    diff_result = diff_contracts(code_result.majority_contract, test_result.majority_contract)
    contracts_dir = artifacts_root / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    (contracts_dir / "diff.json").write_text(
        json.dumps(diff_result.to_dict(), indent=2)
    )

    # Aggregate F5 summary
    (artifacts_root / "f5_summary.json").write_text(json.dumps({
        "mode": mode,
        "k": k,
        "code_author": code_result.summary(),
        "test_author": test_result.summary(),
        "contract_diff": {
            "ok": diff_result.ok,
            "summary": diff_result.summary,
        },
    }, indent=2))

    return artifacts_root / "output"


# ---- per-persona orchestration ------------------------------------------------

def _run_persona(
    coord: Coordinator,
    persona: str,
    context: str,
    *,
    k: int,
    force: bool,
) -> PersonaResult:
    """Call `persona` K times in parallel; validate-and-retry each; K-vote contracts."""
    prompt_path = PERSONA_PROMPT[persona]
    base_prompt = prompt_path.read_text()

    if k <= 1:
        # Single call (still validates-and-retries up to MAX_VALIDATE_RETRIES).
        contract, files, raw, valid = _single_persona_call(
            coord, base_prompt, context, persona, force=force, kvote_idx=0, k_total=1,
        )
        return PersonaResult(
            persona=persona, k=1,
            contracts=[contract], files=[files], raw_responses=[raw],
            majority_contract=contract,
            field_agreement={}, divergent_fields=[],
            contract_valid=[valid], chosen_files_index=0,
        )

    # K parallel calls. force=True so the cache key (identical across K) isn't
    # short-circuited; we want K distinct Codex invocations.
    with concurrent.futures.ThreadPoolExecutor(max_workers=k) as pool:
        futures = [
            pool.submit(
                _single_persona_call,
                coord, base_prompt, context, persona,
                force=True, kvote_idx=i, k_total=k,
            )
            for i in range(k)
        ]
        results = [f.result() for f in futures]

    contracts = [r[0] for r in results]
    files_list = [r[1] for r in results]
    raws = [r[2] for r in results]
    valids = [r[3] for r in results]

    from harness.contract.kvote import kvote
    kv = kvote(contracts)

    # Pick the files-tree from the K-run whose contract most-closely matches
    # the K-vote majority. Tie-break to index 0.
    chosen_idx = _pick_majority_run(contracts, kv.majority)

    return PersonaResult(
        persona=persona, k=k,
        contracts=contracts, files=files_list, raw_responses=raws,
        majority_contract=kv.majority,
        field_agreement=kv.field_agreement, divergent_fields=kv.divergent_fields,
        contract_valid=valids, chosen_files_index=chosen_idx,
    )


def _single_persona_call(
    coord: Coordinator,
    base_prompt: str,
    context: str,
    persona: str,
    *,
    force: bool,
    kvote_idx: int,
    k_total: int,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any], bool]:
    """One Codex call with validate-and-retry. Returns (contract, files_dict, raw_response, contract_valid)."""
    from harness.contract.validate import validate

    current_prompt = base_prompt
    # When K>1, add a benign run-marker so even at temp=0 the model has a tiny
    # input perturbation; in practice this rarely changes output, but it
    # ensures the K calls aren't truly identical bytes-in.
    if k_total > 1:
        current_prompt = f"{base_prompt}\n\n<!-- k-vote run {kvote_idx + 1} of {k_total} -->\n"

    last_response: dict[str, Any] = {}
    last_files: dict[str, str] = {}
    last_contract: dict[str, Any] = {}
    contract_valid = False

    for attempt in range(MAX_VALIDATE_RETRIES + 1):
        last_response = coord.call_codex(
            prompt=current_prompt, context=context, force=(force or attempt > 0),
        )
        final_message = str(last_response.get("final_message") or last_response.get("stdout") or "")
        last_files, last_contract = _parse_response(final_message)
        if last_contract is None:
            current_prompt = (
                base_prompt
                + f"\n\n<!-- k-vote run {kvote_idx + 1} of {k_total} -->\n"
                + "\n\nRETRY: Your previous response did not contain a parseable JSON contract block. "
                + "Emit the complete Java + the contracts/public-contract."
                + persona
                + ".json block as required by the persona spec."
            )
            last_contract = {}
            continue
        validation = validate(last_contract)
        if validation.ok:
            contract_valid = True
            break
        # Attach the retry-prompt as a postscript to nudge the persona.
        current_prompt = (
            base_prompt
            + f"\n\n<!-- k-vote run {kvote_idx + 1} of {k_total} -->\n"
            + "\n\n"
            + validation.retry_prompt
        )

    return last_contract or {}, last_files, last_response, contract_valid


def _parse_response(text: str) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Extract Java + xml + text + contract blocks from one Codex response.

    Returns (files_dict, contract_or_None). files_dict maps relpath -> body.
    """
    files: dict[str, str] = {}
    for m in JAVA_BLOCK.finditer(text):
        files[m.group("path").strip()] = m.group("body")
    for m in XML_BLOCK.finditer(text):
        files[m.group("path").strip()] = m.group("body")
    for m in TEXT_BLOCK.finditer(text):
        files[m.group("path").strip()] = m.group("body")

    contract_match = JSON_CONTRACT_BLOCK.search(text)
    if not contract_match:
        return files, None
    body = contract_match.group("body").strip()
    try:
        return files, json.loads(body)
    except json.JSONDecodeError:
        return files, None


def _pick_majority_run(contracts: list[dict[str, Any]], majority: dict[str, Any]) -> int:
    """Pick the K-run whose contract best matches the majority.

    Crude metric: count exact-key-value matches at top-level. Tie-break to 0.
    """
    if not contracts:
        return 0
    best_idx = 0
    best_score = -1
    for i, c in enumerate(contracts):
        score = sum(1 for k, v in c.items() if k in majority and majority[k] == v)
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx


# ---- artifact persistence ---------------------------------------------------

def _save_persona(artifacts_root: Path, result: PersonaResult) -> None:
    output_dir = artifacts_root / "output"
    contracts_dir = artifacts_root / "contracts"
    raw_dir = artifacts_root / "raw" / result.persona
    contracts_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Write the chosen K-run's files.
    chosen_files = result.files[result.chosen_files_index] if result.files else {}
    for relpath, body in chosen_files.items():
        target = output_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)

    # Write the majority contract.
    contract_path = contracts_dir / f"public-contract.{result.persona}.json"
    contract_path.write_text(
        json.dumps(result.majority_contract, indent=2, sort_keys=True)
    )

    # Per-K K-vote metadata (if K>1).
    if result.k > 1:
        kvote_path = contracts_dir / f"kvote-metadata.{result.persona}.json"
        kvote_path.write_text(json.dumps({
            "k": result.k,
            "field_agreement": result.field_agreement,
            "divergent_fields": result.divergent_fields,
            "contract_valid_per_run": result.contract_valid,
            "chosen_run_index": result.chosen_files_index,
        }, indent=2))

    # Raw responses per K (for forensics).
    for i, raw in enumerate(result.raw_responses):
        (raw_dir / f"response-{i}.json").write_text(
            json.dumps(raw, indent=2, default=str)
        )


def _save_backcompat_codex_response(artifacts_root: Path, code_result: PersonaResult) -> None:
    """Keep `codex_response.json` at the run root for tools that still read wave-1/2's path."""
    if not code_result.raw_responses:
        return
    raw = code_result.raw_responses[code_result.chosen_files_index]
    (artifacts_root / "codex_response.json").write_text(
        json.dumps(raw, indent=2, default=str)
    )
