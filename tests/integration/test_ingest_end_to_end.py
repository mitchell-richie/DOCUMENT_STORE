"""End-to-end tests: CLI, config file, and SQLite database together."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from document_store.db.connection import connect
from document_store.ingest.cli import EXIT_CONFIG_ERROR, EXIT_OK, main

pytestmark = pytest.mark.integration


def _db(project: Path) -> sqlite3.Connection:
    return connect(project / "case.sqlite")


def _documents(project: Path) -> dict[str, tuple[str, str]]:
    conn = _db(project)
    try:
        rows = conn.execute(
            "SELECT title, doc_class, processing_route FROM document"
        ).fetchall()
        return {row["title"]: (row["doc_class"], row["processing_route"]) for row in rows}
    finally:
        conn.close()


def test_fresh_ingest_creates_expected_documents(project: Path) -> None:
    assert main([]) == EXIT_OK

    assert _documents(project) == {
        "order.pdf": ("in_camera", "local_only"),
        "letter.docx": ("correspondence", "standard"),
        "bank_statement_synthetic_2024-01.pdf": ("financial_statement", "external"),
    }


def test_unsupported_file_creates_no_rows(project: Path) -> None:
    main([])
    assert "notes.txt" not in {title for title in _documents(project)}


def test_rerun_is_idempotent(project: Path) -> None:
    main([])
    before = _documents(project)

    assert main([]) == EXIT_OK
    assert _documents(project) == before


def test_every_document_has_a_source_file(project: Path) -> None:
    main([])
    conn = _db(project)
    try:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM document WHERE source_file_id NOT IN (SELECT id FROM source_file)"
        ).fetchone()[0]
        unlocated = conn.execute(
            "SELECT COUNT(*) FROM source_file sf "
            "WHERE NOT EXISTS (SELECT 1 FROM source_file_location l WHERE l.source_file_id = sf.id)"
        ).fetchone()[0]
    finally:
        conn.close()

    assert orphans == 0
    assert unlocated == 0


def test_path_outside_originals_is_rejected(project: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    assert main([str(outside)]) == EXIT_CONFIG_ERROR
    assert not (project / "case.sqlite").exists() or _documents(project) == {}


def test_missing_config_is_a_configuration_error(project: Path) -> None:
    assert main(["--config", str(project / "absent.toml")]) == EXIT_CONFIG_ERROR


def test_module_entry_point_runs(project: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "document_store.ingest", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Ingest case documents" in result.stdout