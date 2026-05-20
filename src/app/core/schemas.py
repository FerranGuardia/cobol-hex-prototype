"""Pydantic schemas for artifacts that cross phase boundaries."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class RunConfig(BaseModel):
    """Resolved configuration for a run; built once at CLI entry."""

    corpus_root: Path
    codex_bin: str
    model: str
    reasoning_effort: str = "high"  # none|low|medium|high|xhigh
    temperature: float = 0.0
    seed: int = 42
    cache_dir: Path
    artifacts_dir: Path
    timeout_seconds: int = 600


class InventoryEntry(BaseModel):
    path: Path
    kind: Literal["cbl", "cpy", "jcl", "ddl", "dcl", "bms", "ctl", "csd", "other"]
    lines: int
    complexity_score: int = 0
    sub_application: str | None = None


class Inventory(BaseModel):
    scanned_at: datetime
    corpus_root: Path
    slice_name: str | None = None
    entries: list[InventoryEntry] = Field(default_factory=list)


class GoldenMasterAssertion(BaseModel):
    """One I/O assertion derived from documented behavior."""

    name: str
    description: str
    input_fixture: Path | None = None
    expected_output: str | dict | list | None = None
    kind: Literal["batch_output", "sql_sequence", "exit_code", "file_diff"] = "batch_output"


class GoldenMaster(BaseModel):
    program: str
    source_file: Path
    assertions: list[GoldenMasterAssertion] = Field(default_factory=list)


class TierResult(BaseModel):
    status: Literal["pass", "fail", "skip"]
    score: float | None = None
    failure_tags: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class ValidationReport(BaseModel):
    run_id: str
    source_file: Path
    t1: TierResult
    t2: TierResult
    t3: TierResult
    t4: TierResult
    overall: Literal["pass", "fail"]


class RunManifest(BaseModel):
    """Sidecar manifest for one `app run` invocation."""

    run_id: str
    source_file: Path
    started_at: datetime
    config: RunConfig
    git_sha: str | None = None
