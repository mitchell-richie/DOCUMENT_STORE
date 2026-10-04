"""End-to-end tests for the ingestion run log."""

import json
import sqlite3
from pathlib import Path

import pytest

from document_store.db.connection import connect
from document_store.ingest import pipeline
from document_store.ingest.cli import EXIT_OK, EXIT_UNEXPECTED, main

pytestmark = pytest.mark.integration


def _runs(project: Path) -> list[sqlite3.Row]:
    conn = connect(project / "case.sqlite")
    try:
        return conn.execute("SELECT * FROM processing_run ORDER BY id").fetchall()
    finally:
        conn.close()


def test_successful_run_is_recorded_with_summary(project: Path) -> None:
    assert main([]) == EXIT_OK

    (run,) = _runs(project)
    assert run["stage"] == "ingest"
    assert run["finished_at"] is not None
    summary = json.loads(run["parameters"])["summary"]
    assert summary["documents_created"] == 3
    assert summary["files_skipped"] == 1
    assert summary["files_failed"] == []


def test_log_file_is_written_without_document_text(project: Path) -> None:
    main([])

    (run,) = _runs(project)
    log_path = Path(json.loads(run["parameters"])["log_file"])
    assert log_path.parent == project / "logs"

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    messages = [r["message"] for r in records]
    assert any("skipping unsupported file: notes.txt" in m for m in messages)
    assert all("Synthetic native page" not in m for m in messages)


def test_crashed_run_leaves_finished_at_unset(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(pipeline, "ingest_folder", boom)
    from document_store.ingest import cli

    monkeypatch.setattr(cli, "ingest_folder", boom)

    assert main([]) == EXIT_UNEXPECTED

    (run,) = _runs(project)
    assert run["finished_at"] is None


def test_each_run_gets_its_own_record(project: Path) -> None:
    main([])
    main([])
    assert len(_runs(project)) == 2