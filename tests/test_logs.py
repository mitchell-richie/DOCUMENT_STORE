"""Tests for the shared logging module (STORY-11.4)."""

import json
import logging
from pathlib import Path

import pytest

from document_store.logs import configure_console, run_log_file


def test_run_log_file_writes_json_lines(tmp_path: Path) -> None:
    logger = logging.getLogger("test.logs")
    with run_log_file(tmp_path / "logs", "demo", "stamp") as path:
        logger.info("hello from the run")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "hello from the run"
    assert record["level"] == "INFO"
    assert record["logger"] == "test.logs"
    assert "time" in record


def test_run_log_file_includes_exception_text(tmp_path: Path) -> None:
    logger = logging.getLogger("test.logs")
    with run_log_file(tmp_path, "demo", "stamp") as path:
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("something failed")
            
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert "ValueError: boom" in record["exc_info"]


def test_run_log_file_restores_root_level(tmp_path: Path) -> None:
    root = logging.getLogger()
    before = root.level
    with run_log_file(tmp_path, "demo", "stamp"):
        pass
    assert root.level == before


def test_run_log_file_removes_its_handler(tmp_path: Path) -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    with run_log_file(tmp_path, "demo", "stamp"):
        pass
    assert root.handlers == before


def test_configure_console_is_idempotent() -> None:
    configure_console()
    configure_console()
    root = logging.getLogger()
    markers = [h for h in root.handlers if getattr(h, "_document_store_console", False)]
    assert len(markers) == 1


@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG])
def test_configure_console_sets_root_level(level: int) -> None:
    configure_console(level)
    assert logging.getLogger().level <= level