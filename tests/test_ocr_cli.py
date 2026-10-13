"""Tests for the OCR command line (STORY-3.9)."""

import json
from pathlib import Path

from conftest import LOW_CONFIDENCE_TEXT, seed_ocr_cache
from document_store.db.connection import connect
from document_store.db.migrate import migrate
from document_store.extract import ocr_cli
from document_store.extract.ocr import OcrCache
from document_store.extract.pdf import extract_pdf
from document_store.ingest.documents import create_or_update_document
from document_store.ingest.register import register_file, sha256_of


def _fail() -> None:
    raise AssertionError("OCR engine should not be created; results are cached")


def test_ocr_run_flags_document_and_records_run(
    config_file: Path, tmp_path: Path, fixtures_dir: Path, monkeypatch
) -> None:
    monkeypatch.setattr(ocr_cli, "create_engine", _fail)
    scan = fixtures_dir / "scanned.pdf"

    connection = connect(tmp_path / "case.sqlite")
    try:
        migrate(connection)
        source = register_file(connection, scan).source_file_id
        document_id = create_or_update_document(
            connection, source, "correspondence", "standard", "scanned.pdf"
        ).document_id
    finally:
        connection.close()
    cache = OcrCache(tmp_path / "cache", dpi=200)
    seed_ocr_cache(cache, sha256_of(scan), extract_pdf(scan).pages_needing_ocr)

    assert ocr_cli.main(["--config", str(config_file)]) == ocr_cli.EXIT_OK

    connection = connect(tmp_path / "case.sqlite")
    try:
        run = connection.execute(
            "SELECT model_id, parameters, finished_at FROM processing_run WHERE stage = 'ocr'"
        ).fetchone()
        flag = connection.execute(
            "SELECT low_confidence FROM document WHERE id = ?", (document_id,)
        ).fetchone()["low_confidence"]
    finally:
        connection.close()

    assert flag == 1
    assert run["finished_at"] is not None
    assert run["model_id"] == cache.engine_tag
    parameters = json.loads(run["parameters"])
    assert parameters["confidence_threshold"] == 0.6
    assert parameters["summary"]["documents_flagged"] == 1

    # Privacy rule: OCR text never reaches the run log.
    logs = list((tmp_path / "logs").glob("ocr-*.log"))
    assert len(logs) == 1
    assert LOW_CONFIDENCE_TEXT not in logs[0].read_text(encoding="utf-8")