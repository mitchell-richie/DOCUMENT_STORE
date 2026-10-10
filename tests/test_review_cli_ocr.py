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

CONFIG = """
[paths]
project_dir = "{project_dir}"
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
min_text_chars = 20
dpi = 200

[classification]
default_doc_class = "unclassified"

[routing]
in_camera = "local_only"
financial_statement = "external"
receipt = "standard"
court_filing = "standard"
correspondence = "standard"
other = "standard"
unclassified = "local_only"
"""


@pytest.fixture
def project(tmp_path: Path, fixtures_dir: Path, monkeypatch) -> tuple[str, int]:
    """A config file and database holding one document with a flagged page."""
    monkeypatch.setenv("LLM_GATEWAY_KEY", "test-key")
    config = tmp_path / "config.toml"
    config.write_text(CONFIG.format(project_dir=tmp_path.as_posix()), encoding="utf-8")

    connection = connect(tmp_path / "case.sqlite")
    try:
        migrate(connection)
        source = register_file(connection, fixtures_dir / "scanned.pdf").source_file_id
        document_id = create_or_update_document(
            connection, source, "correspondence", "standard", "scanned.pdf"
        ).document_id
        low_confidence_page_number = 1
        low_confidence_page = OcrPage(
            page_number=low_confidence_page_number,
            text="Smudged words",
            mean_confidence=0.31
            )
        record_ocr_pages(
            connection,
            document_id,
            [low_confidence_page],
            [low_confidence_page_number],
            engine_tag="test-tag",
        )
    finally:
        connection.close()
    return str(config), document_id


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