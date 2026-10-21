"""Tests for the OCR run over registered documents (STORY-3.9)."""

import shutil
from pathlib import Path

import pytest
from PIL import Image

from conftest import LowConfidenceScan, NoEngine, seed_ocr_cache
from document_store.extract.ocr import OcrCache
from document_store.extract.ocr_pipeline import ocr_documents
from document_store.ingest.documents import create_or_update_document
from document_store.ingest.ocr_flags import list_flagged
from document_store.ingest.register import register_file, sha256_of

THRESHOLD = 0.6


def test_low_confidence_scan_is_flagged(conn, low_confidence_scan: LowConfidenceScan) -> None:
    summary = ocr_documents(conn, NoEngine(), low_confidence_scan.cache, THRESHOLD)

    assert summary.documents_processed == 1
    assert summary.pages_ocrd == len(low_confidence_scan.pages)
    assert summary.documents_flagged == 1
    assert summary.errors == []
    assert {f.document_id for f in list_flagged(conn)} == {low_confidence_scan.document_id}


def test_low_confidence_image_is_flagged(conn, tmp_path: Path) -> None:
    path = tmp_path / "scan.png"
    Image.new("RGB", (200, 80), "white").save(path)
    source = register_file(conn, path).source_file_id
    document_id = create_or_update_document(
        conn, source, "receipt", "standard", "scan.png"
    ).document_id
    cache = OcrCache(tmp_path / "cache")
    seed_ocr_cache(cache, sha256_of(path), [1])

    summary = ocr_documents(conn, NoEngine(), cache, THRESHOLD)

    assert summary.documents_flagged == 1
    assert [(f.document_id, f.page_number) for f in list_flagged(conn)] == [(document_id, 1)]


def test_documents_without_scans_are_not_flagged(conn, fixtures_dir: Path, tmp_path: Path) -> None:
    for name in ("native.pdf", "sample.docx"):
        source = register_file(conn, fixtures_dir / name).source_file_id
        create_or_update_document(conn, source, "correspondence", "standard", name)

    summary = ocr_documents(conn, NoEngine(), OcrCache(tmp_path / "cache"), THRESHOLD)

    assert summary.documents_processed == 1  # the PDF; Word documents are not candidates
    assert summary.pages_ocrd == 0
    assert summary.documents_flagged == 0


@pytest.mark.parametrize("route", ["external", "index_only"])
def test_routes_without_content_processing_are_skipped(
    conn, fixtures_dir: Path, tmp_path: Path, route: str
) -> None:
    source = register_file(conn, fixtures_dir / "scanned.pdf").source_file_id
    create_or_update_document(conn, source, "financial_statement", route, "scanned.pdf")

    summary = ocr_documents(conn, NoEngine(), OcrCache(tmp_path / "cache"), THRESHOLD)

    assert summary.documents_processed == 0
    assert summary.errors == []


def test_missing_original_is_reported_and_run_continues(
    conn, low_confidence_scan: LowConfidenceScan, fixtures_dir: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "gone.pdf"
    shutil.copy(fixtures_dir / "native.pdf", copy)
    source = register_file(conn, copy).source_file_id
    create_or_update_document(conn, source, "correspondence", "standard", "gone.pdf")
    copy.unlink()

    summary = ocr_documents(conn, NoEngine(), low_confidence_scan.cache, THRESHOLD)

    assert [title for title, _ in summary.errors] == ["gone.pdf"]
    assert summary.documents_processed == 1
    assert summary.documents_flagged == 1


def test_changed_original_is_not_processed(conn, fixtures_dir: Path, tmp_path: Path) -> None:
    copy = tmp_path / "changed.pdf"
    shutil.copy(fixtures_dir / "scanned.pdf", copy)
    source = register_file(conn, copy).source_file_id
    create_or_update_document(conn, source, "correspondence", "standard", "changed.pdf")
    shutil.copy(fixtures_dir / "native.pdf", copy)  # content no longer matches the hash

    summary = ocr_documents(conn, NoEngine(), OcrCache(tmp_path / "cache"), THRESHOLD)

    assert summary.documents_processed == 0
    assert [title for title, _ in summary.errors] == ["changed.pdf"]