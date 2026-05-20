"""Smoke tests — verify the skeleton imports + produces artifacts without an LLM call."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.core.schemas import RunConfig
from app.pipeline import context_pack, golden_master, inventory


@pytest.fixture()
def fake_corpus(tmp_path: Path) -> Path:
    sub = tmp_path / "app" / "app-test"
    (sub / "cbl").mkdir(parents=True)
    (sub / "ddl").mkdir()
    (sub / "dcl").mkdir()
    (sub / "jcl").mkdir()
    (sub / "cbl" / "TESTPGM.cbl").write_text(
        "      IDENTIFICATION DIVISION.\n"
        "      PROGRAM-ID. TESTPGM.\n"
        "      PROCEDURE DIVISION.\n"
        "          EXEC SQL SELECT 1 FROM DUAL END-EXEC.\n"
        "          DISPLAY 'HELLO'.\n"
        "          STOP RUN.\n"
    )
    (sub / "ddl" / "T.ddl").write_text("CREATE TABLE FOO (X INT);")
    (sub / "dcl" / "D.dcl").write_text("  01 D-FOO PIC X(10).")
    (sub / "jcl" / "J.jcl").write_text("//STEP1 DD DSN=AWS.M2.FOO")
    (sub / "README.md").write_text("# Test\n## Features\n- thing one\n- thing two\n")
    return tmp_path


def _cfg(tmp: Path, corpus: Path) -> RunConfig:
    return RunConfig(
        corpus_root=corpus,
        codex_bin="codex",
        model="x",
        temperature=0,
        seed=42,
        cache_dir=tmp / ".cache",
        artifacts_dir=tmp / "artifacts",
        timeout_seconds=60,
    )


def test_inventory_emits_json(fake_corpus: Path, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, fake_corpus)
    out = inventory.scan(cfg, "app-test")
    data = json.loads(out.read_text())
    assert any(e["path"].endswith("TESTPGM.cbl") for e in data["entries"])


def test_context_pack_includes_sections(fake_corpus: Path, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, fake_corpus)
    source = fake_corpus / "app" / "app-test" / "cbl" / "TESTPGM.cbl"
    out = context_pack.build(cfg, "smoke", source)
    text = out.read_text()
    assert "COBOL source" in text
    assert "TESTPGM" in text
    assert "DB2 host variable declarations" in text
    assert "DB2 table DDL" in text
    assert "JCL (batch workflow)" in text


def test_golden_master_extracts_assertions(fake_corpus: Path, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, fake_corpus)
    source = fake_corpus / "app" / "app-test" / "cbl" / "TESTPGM.cbl"
    out = golden_master.build(cfg, "smoke", source)
    data = json.loads(out.read_text())
    assertions = data["assertions"]
    assert any("ddl-table" in a["name"] for a in assertions)
    assert any("jcl-" in a["name"] for a in assertions)
    assert any("readme-feature" in a["name"] for a in assertions)
