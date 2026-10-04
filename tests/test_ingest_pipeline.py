"""Tests for the ingestion pipeline (STORY-2.6)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from document_store.ingest.pipeline import check_within_originals, ingest_folder


def _routes(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    rows = conn.execute("SELECT title, doc_class, processing_route FROM document").fetchall()
    return {row["title"]: (row["doc_class"], row["processing_route"]) for row in rows}


def test_ingest_creates_documents_with_class_and_route(
    conn: sqlite3.Connection, classifier, router, originals: Path
) -> None:
    summary = ingest_folder(conn, classifier, router, originals, originals)

    assert summary.documents_created == 2
    assert [p.name for p in summary.skipped] == ["notes.txt"]
    assert summary.errors == []
    assert _routes(conn) == {
        "order.pdf": ("in_camera", "local_only"),
        "letter.docx": ("correspondence", "standard"),
    }


def test_rerun_creates_nothing(conn, classifier, router, originals: Path) -> None:
    ingest_folder(conn, classifier, router, originals, originals)
    summary = ingest_folder(conn, classifier, router, originals, originals)

    assert summary.documents_created == 0
    assert summary.documents_existing == 2


def test_same_content_in_two_classes_takes_most_restrictive(
    conn, classifier, router, originals: Path, fixtures_dir: Path
) -> None:
    shutil.copy(fixtures_dir / "native.pdf", originals / "correspondence" / "order-copy.pdf")
    summary = ingest_folder(conn, classifier, router, originals, originals)

    assert summary.documents_created == 2
    # Both copies share content, so one source file; the route is local_only either way.
    assert conn.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 2
    assert _routes(conn)["order.pdf"][1] == "local_only"


def test_failure_on_one_file_does_not_stop_the_run(
    conn, classifier, router, originals: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from document_store.ingest import pipeline

    real = pipeline.ingest_file

    def flaky(conn, classifier, router, originals_root, path):
        if path.name == "letter.docx":
            raise OSError("simulated read failure")
        return real(conn, classifier, router, originals_root, path)

    monkeypatch.setattr(pipeline, "ingest_file", flaky)
    summary = ingest_folder(conn, classifier, router, originals, originals)

    assert summary.documents_created == 1
    assert [p.name for p, _ in summary.errors] == ["letter.docx"]


def test_path_outside_originals_is_rejected(tmp_path: Path) -> None:
    originals = tmp_path / "originals"
    originals.mkdir()
    with pytest.raises(ValueError):
        check_within_originals(originals, tmp_path / "elsewhere")