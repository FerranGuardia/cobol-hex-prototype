"""CLI entry point. See README.md for usage."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

from app.core.coordinator import Coordinator
from app.core.schemas import RunConfig
from app.pipeline import context_pack, convert, golden_master, inventory, validate

load_dotenv()
console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=True, help="COBOL -> hex Java pipeline")


def _config_from_env() -> RunConfig:
    corpus = os.environ.get("COBOL_CORPUS")
    if not corpus:
        console.print("[red]COBOL_CORPUS not set. Set it in .env or as an env var.[/red]")
        raise typer.Exit(2)
    return RunConfig(
        corpus_root=Path(corpus).resolve(),
        codex_bin=os.environ.get("CODEX_BIN", "codex"),
        model=os.environ.get("LLM_MODEL", ""),  # blank = let Codex pick default
        reasoning_effort=os.environ.get("LLM_REASONING_EFFORT", "high"),
        temperature=float(os.environ.get("LLM_TEMPERATURE", "0")),
        seed=int(os.environ.get("LLM_SEED", "42")),
        cache_dir=Path(os.environ.get("CACHE_DIR", ".cache")).resolve(),
        artifacts_dir=Path(os.environ.get("ARTIFACTS_DIR", "artifacts")).resolve(),
        timeout_seconds=int(os.environ.get("LLM_TIMEOUT_SECONDS", "600")),
    )


@app.command("inventory")
def cmd_inventory(
    slice_name: str = typer.Option(..., "--slice", help="Sub-application directory under app/"),
) -> None:
    """F1 — scan a corpus slice and emit inventory.json."""
    cfg = _config_from_env()
    out = inventory.scan(cfg, slice_name)
    console.print(f"[green]inventory written:[/green] {out}")


@app.command("context-pack")
def cmd_context_pack(
    file: Path = typer.Option(..., "--file", exists=True, help="COBOL .cbl to pack"),
    run_id: str = typer.Option(None, "--run-id", help="Run id (auto if omitted)"),
) -> None:
    """F3 — build a deterministic context pack for a single source file."""
    cfg = _config_from_env()
    coord = Coordinator(cfg)
    run_id = run_id or coord.new_run_id(file)
    out = context_pack.build(cfg, run_id, file)
    console.print(f"[green]context pack written:[/green] {out}")


@app.command("convert")
def cmd_convert(
    file: Path = typer.Option(..., "--file", exists=True, help="COBOL .cbl to convert"),
    run_id: str = typer.Option(None, "--run-id"),
    force: bool = typer.Option(False, "--force", help="Bypass cache"),
    k: int = typer.Option(1, "--k", min=1, max=11, help="K-vote runs per persona (1 = single call)"),
    mode: str = typer.Option(
        "two-pass-blind", "--mode",
        help="two-pass-blind (code-author ‖ test-author) | single-pass (code-author only, legacy)",
    ),
) -> None:
    """F5 — two-pass orchestrator. Runs code-author + test-author independently and diffs their contracts."""
    cfg = _config_from_env()
    coord = Coordinator(cfg)
    run_id = run_id or coord.new_run_id(file)
    out_dir = convert.run(cfg, run_id, file, force=force, k=k, mode=mode)  # type: ignore[arg-type]
    console.print(f"[green]converted output:[/green] {out_dir}")


@app.command("validate")
def cmd_validate(
    run_id: str = typer.Option(..., "--run-id"),
    source_file: Path | None = typer.Option(None, "--file", help="Source file for the report (optional)"),
) -> None:
    """F6 — validate a run against the four acceptance tiers."""
    cfg = _config_from_env()
    report = validate.run(cfg, run_id, source_file=source_file)
    console.print_json(json.dumps(report.model_dump(mode="json")))
    if report.t1.status != "pass":
        raise typer.Exit(1)


@app.command("run")
def cmd_run(
    file: Path = typer.Option(..., "--file", exists=True, help="COBOL .cbl to convert"),
    force: bool = typer.Option(False, "--force", help="Bypass cache for every phase"),
    k: int = typer.Option(1, "--k", min=1, max=11, help="K-vote runs per persona"),
    mode: str = typer.Option(
        "two-pass-blind", "--mode",
        help="two-pass-blind | single-pass",
    ),
) -> None:
    """End-to-end: F3 -> F4 -> F5 (two-pass) -> F6 (validate + drift-check) on one file."""
    cfg = _config_from_env()
    coord = Coordinator(cfg)
    run_id = coord.new_run_id(file)
    console.rule(f"[bold]run {run_id}  mode={mode}  k={k}[/bold]")
    context_pack.build(cfg, run_id, file)
    golden_master.build(cfg, run_id, file)
    convert.run(cfg, run_id, file, force=force, k=k, mode=mode)  # type: ignore[arg-type]
    report = validate.run(cfg, run_id, source_file=file)
    console.print_json(json.dumps(report.model_dump(mode="json")))

    # Drift checks (deterministic, no extra Codex) — run automatically after validate.
    try:
        from harness.checks.drift_checks import run_all as drift_run_all
        from harness.extract.cobol_facts import extract as extract_cobol_facts

        output_root = cfg.artifacts_dir / run_id / "output"
        candidates = list(output_root.rglob("domain"))
        java_root = candidates[0].parent if candidates else output_root
        facts = extract_cobol_facts(file)
        drift = drift_run_all(facts, java_root)
        (cfg.artifacts_dir / run_id / "drift.json").write_text(
            json.dumps(drift.to_dict(), indent=2)
        )
        console.rule("[bold]drift-check[/bold]")
        console.print_json(json.dumps(drift.to_dict(), indent=2))
    except Exception as exc:  # pragma: no cover — best-effort post-step
        console.print(f"[yellow]drift-check skipped:[/yellow] {exc}")

    # Contract diff (if both personas produced contracts) — also automatic.
    if mode == "two-pass-blind":
        try:
            from harness.contract.diff import diff_contracts

            code_path = cfg.artifacts_dir / run_id / "contracts" / "public-contract.code-author.json"
            test_path = cfg.artifacts_dir / run_id / "contracts" / "public-contract.test-author.json"
            if code_path.exists() and test_path.exists():
                code_contract = json.loads(code_path.read_text())
                test_contract = json.loads(test_path.read_text())
                diff_result = diff_contracts(code_contract, test_contract)
                (cfg.artifacts_dir / run_id / "contracts" / "diff.json").write_text(
                    json.dumps(diff_result.to_dict(), indent=2)
                )
                console.rule("[bold]contract-diff[/bold]")
                console.print_json(json.dumps(diff_result.to_dict(), indent=2))
        except Exception as exc:  # pragma: no cover
            console.print(f"[yellow]contract-diff skipped:[/yellow] {exc}")


@app.command("drift")
def cmd_drift(
    file: Path = typer.Option(..., "--file", exists=True),
    runs: int = typer.Option(3, "--runs", min=2, max=10),
) -> None:
    """T3 — run the converter N times on the same input and report divergence."""
    cfg = _config_from_env()
    coord = Coordinator(cfg)
    report = coord.drift(file, runs=runs)
    console.print_json(json.dumps(report))


# -- Phase A harness commands (deterministic, no Codex) -----------------------

@app.command("extract-facts")
def cmd_extract_facts(
    file: Path = typer.Option(..., "--file", exists=True, help="COBOL .cbl to extract facts from"),
    out: Path | None = typer.Option(None, "--out", help="Where to write facts.json (default: stdout)"),
) -> None:
    """Mechanically extract structural facts from a COBOL source.

    No LLM. Produces a facts.json that downstream drift_checks consumes.
    """
    from harness.extract.cobol_facts import extract

    facts = extract(file)
    facts_json = json.dumps(facts.to_dict(), indent=2, default=str)
    if out:
        out.write_text(facts_json)
        console.print(f"[green]facts written:[/green] {out}")
    else:
        console.print_json(facts_json)


@app.command("validate-contract")
def cmd_validate_contract(
    run_id: str = typer.Option(..., "--run-id"),
    persona: str = typer.Option(
        "code-author", "--persona",
        help="code-author | test-author | kvote-majority",
    ),
) -> None:
    """Validate a generated public-contract.json against schema + canonical form.

    Exits non-zero if the contract is invalid (so it can be used in CI / pre-commit).
    """
    from harness.contract.validate import validate

    cfg = _config_from_env()
    contract_path = (
        cfg.artifacts_dir / run_id / "contracts" / f"public-contract.{persona}.json"
    )
    if not contract_path.exists():
        console.print(f"[red]contract not found:[/red] {contract_path}")
        raise typer.Exit(2)
    contract = json.loads(contract_path.read_text())
    result = validate(contract)
    console.print_json(json.dumps(result.to_dict(), indent=2))
    if not result.ok:
        raise typer.Exit(1)


@app.command("drift-check")
def cmd_drift_check(
    run_id: str = typer.Option(..., "--run-id"),
    file: Path = typer.Option(..., "--file", exists=True, help="Original COBOL source"),
) -> None:
    """Run mechanical drift checks against the generated Java tree.

    Catches the wave-2 observed drifts: file-org, abend-catchable, path-leak,
    charset-implicit, duplicated-output. Exits non-zero on any `fail`-severity finding.
    """
    from harness.checks.drift_checks import run_all
    from harness.extract.cobol_facts import extract

    cfg = _config_from_env()
    output_root = cfg.artifacts_dir / run_id / "output"
    if not output_root.exists():
        console.print(f"[red]output tree not found:[/red] {output_root}")
        raise typer.Exit(2)

    # Drill into the generated package root (skip the com/example/cobol/<slice>/ prefix
    # so per-file paths are reported relative to the slice's package root).
    candidates = list(output_root.rglob("domain"))
    java_root = candidates[0].parent if candidates else output_root

    facts = extract(file)
    report = run_all(facts, java_root)
    console.print_json(json.dumps(report.to_dict(), indent=2))
    if not report.ok:
        raise typer.Exit(1)


@app.command("contract-diff")
def cmd_contract_diff(
    run_id: str = typer.Option(..., "--run-id"),
) -> None:
    """Diff the code-author and test-author contracts for a run.

    Surfaces T2-CONTRACT-MISMATCH findings — the load-bearing signal in the
    two-pass design. Exits non-zero if any `critical` entries exist.
    """
    from harness.contract.diff import diff_contracts

    cfg = _config_from_env()
    code_path = cfg.artifacts_dir / run_id / "contracts" / "public-contract.code-author.json"
    test_path = cfg.artifacts_dir / run_id / "contracts" / "public-contract.test-author.json"
    if not code_path.exists():
        console.print(f"[red]code-author contract not found:[/red] {code_path}")
        raise typer.Exit(2)
    if not test_path.exists():
        console.print(f"[red]test-author contract not found:[/red] {test_path}")
        raise typer.Exit(2)
    code_contract = json.loads(code_path.read_text())
    test_contract = json.loads(test_path.read_text())
    result = diff_contracts(code_contract, test_contract)
    console.print_json(json.dumps(result.to_dict(), indent=2))
    if not result.ok:
        raise typer.Exit(1)


@app.command("ui")
def cmd_ui(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port"),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open the browser"),
) -> None:
    """Launch the editorial observatory dashboard on localhost."""
    from app.ui.server import serve

    cfg = _config_from_env()
    serve(cfg.artifacts_dir, host=host, port=port, open_browser=not no_open)


def main() -> None:  # entry point for `app` script
    try:
        app()
    except KeyboardInterrupt:
        console.print("[yellow]interrupted[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
