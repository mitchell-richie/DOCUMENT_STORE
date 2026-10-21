"""Tests for OCR and the low-confidence judgement in PdfExtractor (STORY-3.9)."""

import pytest

from conftest import LowConfidenceScan, NoEngine, seed_ocr_cache
from document_store.extract.pdf import PdfExtraction, PdfExtractor, extract_pdf

THRESHOLD = 0.6


def _extract(scan: LowConfidenceScan, threshold: float | None = THRESHOLD) -> PdfExtraction:
    return PdfExtractor(
        scan.path,
        source_sha256=scan.sha256,
        engine=NoEngine(),
        cache=scan.cache,
        fallback_threshold=threshold,
    ).extract()


def test_native_only_extraction_has_no_ocr_pages(low_confidence_scan: LowConfidenceScan) -> None:
    extraction = extract_pdf(low_confidence_scan.path)
    assert extraction.ocr_pages == ()
    assert not extraction.low_confidence


def test_low_confidence_pages_are_listed(low_confidence_scan: LowConfidenceScan) -> None:
    extraction = _extract(low_confidence_scan)
    assert [page.page_number for page in extraction.ocr_pages] == low_confidence_scan.pages
    assert list(extraction.low_confidence_pages) == low_confidence_scan.pages
    assert extraction.low_confidence


def test_page_at_threshold_is_not_flagged(low_confidence_scan: LowConfidenceScan) -> None:
    scan = low_confidence_scan
    seed_ocr_cache(scan.cache, scan.sha256, scan.pages, confidence=THRESHOLD)
    assert _extract(scan).low_confidence_pages == ()


def test_page_with_little_text_is_not_flagged(low_confidence_scan: LowConfidenceScan) -> None:
    scan = low_confidence_scan
    seed_ocr_cache(scan.cache, scan.sha256, scan.pages, text="x", confidence=0.1)
    assert _extract(scan).low_confidence_pages == ()


def test_no_threshold_means_no_flags(low_confidence_scan: LowConfidenceScan) -> None:
    assert _extract(low_confidence_scan, threshold=None).low_confidence_pages == ()


def test_ocr_requires_cache_and_hash(low_confidence_scan: LowConfidenceScan) -> None:
    with pytest.raises(ValueError, match="OCR requires"):
        PdfExtractor(low_confidence_scan.path, engine=NoEngine())