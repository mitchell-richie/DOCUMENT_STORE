"""Tests for the OCR review commands of the review CLI (STORY-3.9)."""

from pathlib import Path

import pytest

from document_store.db.connection import connect
from document_store.db.migrate import migrate
from document_store.extract.ocr import OcrPage
from document_store.ingest.documents import create_or_update_document
from document_store.ingest.ocr_flags import record_ocr_pages
from document_store.ingest.register import register_file
from document_store.ingest.review_cli import EXIT_ERROR, EXIT_OK, main


@pytest.fixture
def project(config_file: Path, tmp_path: Path, fixtures_dir: Path) -> tuple[str, int]:
    """A config file and database holding one document with a flagged page."""
    connection = connect(tmp_path / "case.sqlite")
    try:
        migrate(connection)
        source = register_file(connection, fixtures_dir / "scanned.pdf").source_file_id
        document_id = create_or_update_document(
            connection, source, "correspondence", "standard", "scanned.pdf"
        ).document_id
        record_ocr_pages(
            connection,
            document_id,
            [OcrPage(page_number=1, text="", mean_confidence=0.31)],
            [1],
            engine_tag="test-tag",
        )
    finally:
        connection.close()
    return str(config_file), document_id


def test_ocr_list_shows_flagged_page(project, capsys) -> None:
    config, document_id = project

    assert main(["--config", config, "ocr-list"]) == EXIT_OK

    assert capsys.readouterr().out.splitlines() == [
        f"{document_id}\t1\t0.31\tpaddleocr\tscanned.pdf"
    ]


def test_ocr_reviewed_clears_the_flag(project, capsys) -> None:
    config, document_id = project

    assert main(["--config", config, "ocr-reviewed", str(document_id), "--note", "ok"]) == EXIT_OK
    assert "cleared 1 page(s)" in capsys.readouterr().out

    assert main(["--config", config, "ocr-list"]) == EXIT_OK
    assert "No low-confidence pages" in capsys.readouterr().out


def test_ocr_reviewed_unknown_document_is_an_error(project, capsys) -> None:
    config, _ = project

    assert main(["--config", config, "ocr-reviewed", "999"]) == EXIT_ERROR
    assert "No document" in capsys.readouterr().err