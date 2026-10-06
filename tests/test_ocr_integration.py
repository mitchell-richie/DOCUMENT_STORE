"""Integration test: PaddleOCR reads a rendered sample image."""

import shutil
from pathlib import Path

import pytest

from document_store.extract.image import extract_image
from document_store.extract.ocr import OcrCache, ocr_pdf_pages
from document_store.ocr.check import run_check
from document_store.ocr.paddle import create_engine
from document_store.ocr.tesseract import tesseract_ocr

pytestmark = pytest.mark.ocr


def test_sample_image_is_recognised(tmp_path: Path) -> None:
    report = run_check(tmp_path, use_gpu=False)
    assert report.device == "cpu"
    assert "12345" in report.text
    assert report.mean_confidence > 0
    assert report.passed


def test_scanned_pdf_ocr_reads_reference_and_caches(tmp_path: Path, fixtures_dir: Path) -> None:
    engine = create_engine()
    cache = OcrCache(tmp_path / "cache")

    first = ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-int", [1], cache)
    cache_file = cache.path_for("sha-int", 1)
    mtime = cache_file.stat().st_mtime_ns

    second = ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-int", [1], cache)

    assert "54321" in first[0].text
    assert first[0].mean_confidence > 0
    assert second[0].from_cache is True
    assert cache_file.stat().st_mtime_ns == mtime


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
def test_tesseract_reads_receipt(fixtures_dir: Path) -> None:
    result = tesseract_ocr(fixtures_dir / "receipt.png")
    assert "12.50" in result.text




def test_receipt_image_is_read_end_to_end(tmp_path: Path, fixtures_dir: Path) -> None:
    result = extract_image(
        fixtures_dir / "receipt.png",
        source_sha256="sha-receipt",
        engine=create_engine(),
        cache=OcrCache(tmp_path / "cache"),
        fallback_threshold=0.6,
    )

    assert "12.50" in result.page.text
    assert result.needs_vision is False    