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
        model=os.environ.get("LLM_MODEL", "gpt-5-codex"),
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
) -> None:
    """F5 — run the converter on a context pack."""
    cfg = _config_from_env()
    coord = Coordinator(cfg)
    run_id = run_id or coord.new_run_id(file)
    out_dir = convert.run(cfg, run_id, file, force=force)
    console.print(f"[green]converted output:[/green] {out_dir}")


@app.command("validate")
def cmd_validate(
    run_id: str = typer.Option(..., "--run-id"),
) -> None:
    """F6 — validate a run against the four acceptance tiers."""
    cfg = _config_from_env()
    report = validate.run(cfg, run_id)
    console.print_json(json.dumps(report.model_dump()))
    if report.t1.status != "pass":
        raise typer.Exit(1)


@app.command("run")
def cmd_run(
    file: Path = typer.Option(..., "--file", exists=True, help="COBOL .cbl to convert"),
    force: bool = typer.Option(False, "--force", help="Bypass cache for every phase"),
) -> None:
    """End-to-end: F3 -> F4 -> F5 -> F6 on a single file."""
    cfg = _config_from_env()
    coord = Coordinator(cfg)
    run_id = coord.new_run_id(file)
    console.rule(f"[bold]run {run_id}[/bold]")
    context_pack.build(cfg, run_id, file)
    golden_master.build(cfg, run_id, file)
    convert.run(cfg, run_id, file, force=force)
    report = validate.run(cfg, run_id)
    console.print_json(json.dumps(report.model_dump()))


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


def main() -> None:  # entry point for `app` script
    try:
        app()
    except KeyboardInterrupt:
        console.print("[yellow]interrupted[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
