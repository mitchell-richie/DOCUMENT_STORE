"""Fixtures for end-to-end ingestion tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

CONFIG_TEMPLATE = """
[paths]
project_dir = "."
database = "case.sqlite"
originals = "originals"
cache = "cache"
logs = "logs"

[gateway]
url = "http://llm-gateway-api:8000"
client_name = "case-dms"

[models]
embedding = "bge-m3"
embedding_dimensions = 1024
extraction = "qwen2.5:7b-instruct"
generation = "qwen2.5:7b-instruct"

[chunking]
max_chars = 2000
overlap_chars = 200

[ocr]
confidence_threshold = 0.6

[classification]
default_doc_class = "other"

[[classification.rules]]
doc_class = "in_camera"
pattern = "in_camera/**"

[[classification.rules]]
doc_class = "financial_statement"
pattern = "**/bank_statement*"

[[classification.rules]]
doc_class = "correspondence"
pattern = "correspondence/**"

[routing]
in_camera = "local_only"
financial_statement = "external"
receipt = "standard"
court_filing = "standard"
correspondence = "standard"
other = "local_only"
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixtures_dir: Path) -> Path:
    """A project directory with a config file, an originals folder, and fixtures.

    The working directory is set to the project so that relative paths in the
    config resolve inside it.
    """
    monkeypatch.setenv("LLM_GATEWAY_KEY", "test-key")
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(CONFIG_TEMPLATE, encoding="utf-8")

    originals = tmp_path / "originals"
    (originals / "in_camera").mkdir(parents=True)
    (originals / "correspondence").mkdir()

    shutil.copy(fixtures_dir / "native.pdf", originals / "in_camera" / "order.pdf")
    shutil.copy(fixtures_dir / "sample.docx", originals / "correspondence" / "letter.docx")
    shutil.copy(
        fixtures_dir / "bank_statement_synthetic_2024-01.pdf",
        originals / "correspondence" / "bank_statement_synthetic_2024-01.pdf",
    )
    (originals / "correspondence" / "notes.txt").write_text("skip me", encoding="utf-8")
    return tmp_path