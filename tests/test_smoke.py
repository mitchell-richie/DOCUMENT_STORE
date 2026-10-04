"""Smoke tests for project scaffold and configuration loading."""

from pathlib import Path

import pytest

from document_store import __version__
from document_store.config import ConfigError, load_settings

MINIMAL_CONFIG = """
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
extraction = "qwen2.5:7b-instruct"
generation = "qwen2.5:7b-instruct"
embedding_dimensions = 1024

[chunking]
max_chars = 2000
overlap_chars = 200

[ocr]
confidence_threshold = 0.6

[classification]
default_doc_class = "unclassified"

[[classification.rules]]
doc_class = "in_camera"
pattern = "in_camera/**"

[routing]
in_camera = "local_only"
financial_statement = "external"
receipt = "standard"
court_filing = "standard"
correspondence = "standard"
other = "standard"
unclassified = "local_only"
"""


def test_version_is_set() -> None:
    assert __version__


def test_load_settings_reads_toml_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(MINIMAL_CONFIG, encoding="utf-8")
    monkeypatch.setenv("LLM_GATEWAY_KEY", "test-key")

    settings = load_settings(config)

    assert settings.gateway.api_key == "test-key"
    assert settings.models.embedding == "bge-m3"
    assert settings.chunk_max_chars == 2000


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "absent.toml")


def test_missing_api_key_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(MINIMAL_CONFIG, encoding="utf-8")
    monkeypatch.delenv("LLM_GATEWAY_KEY", raising=False)

    with pytest.raises(ConfigError, match="LLM_GATEWAY_KEY"):
        load_settings(config)


def test_malformed_toml_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[paths\nbroken", encoding="utf-8")
    monkeypatch.setenv("LLM_GATEWAY_KEY", "test-key")

    with pytest.raises(ConfigError, match="Malformed"):
        load_settings(config)