"""Tests for low-confidence OCR flagging (STORY-3.9)."""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from document_store.extract.ocr import PADDLE_ENGINE, OcrCache, OcrPage
from document_store.extract.pdf import PdfExtraction, PdfExtractor, extract_pdf
from document_store.ingest.documents import create_or_update_document
from document_store.ingest.ocr_flags import list_flagged, mark_reviewed, record_ocr_pages
from document_store.ingest.register import register_file
from document_store.ocr.tesseract import TESSERACT_ENGINE

THRESHOLD = 0.6
TAG = "paddleocr-test-dpi200"
NEW_TAG = "paddleocr-test-dpi300"


class NoEngine:
    """Fails if OCR is attempted: these tests read results from the cache."""

    def predict(self, input: str) -> None:
        raise AssertionError("OCR engine should not run; the result is cached")


@dataclass(frozen=True)
class LowConfidenceScan:
    document_id: int
    path: Path
    sha256: str
    pages: list[int]
    cache: OcrCache


@pytest.fixture
def document_id(conn: sqlite3.Connection, fixtures_dir: Path) -> int:
    source = register_file(conn, fixtures_dir / "scanned.pdf").source_file_id
    return create_or_update_document(
        conn, source, "correspondence", "standard", "scanned.pdf"
    ).document_id


@pytest.fixture
def low_confidence_scan(
    conn: sqlite3.Connection, document_id: int, fixtures_dir: Path, tmp_path: Path
) -> LowConfidenceScan:
    """The scanned fixture, with a cached low-confidence OCR result per page."""
    path = fixtures_dir / "scanned.pdf"
    sha256 = conn.execute(
        "SELECT s.sha256 FROM source_file s JOIN document d ON d.source_file_id = s.id "
        "WHERE d.id = ?",
        (document_id,),
    ).fetchone()["sha256"]
    pages = extract_pdf(path).pages_needing_ocr
    assert pages, "scanned.pdf should have at least one image-only page"

    cache = OcrCache(tmp_path / "cache")
    for number in pages:
        cache.path_for(sha256, number).write_text(
            json.dumps(
                {"text": "Smudged words from a poor scan", "mean_confidence": 0.31, "engine": PADDLE_ENGINE}
            ),
            encoding="utf-8",
        )
    return LowConfidenceScan(document_id, path, sha256, pages, cache)


def _page(
    number: int,
    confidence: float,
    text: str = "Some recognised words",
    engine: str = PADDLE_ENGINE,
) -> OcrPage:
    return OcrPage(page_number=number, text=text, mean_confidence=confidence, engine=engine)


def _document_flag(conn: sqlite3.Connection, document_id: int) -> int:
    return conn.execute(
        "SELECT low_confidence FROM document WHERE id = ?", (document_id,)
    ).fetchone()["low_confidence"]


def _run(conn: sqlite3.Connection, scan: LowConfidenceScan):
    extraction = PdfExtractor(
        scan.path,
        source_sha256=scan.sha256,
        engine=NoEngine(),
        cache=scan.cache,
        fallback_threshold=THRESHOLD,
    ).extract()
    return record_ocr_pages(
        conn, scan.document_id, extraction.ocr_pages,
        extraction.low_confidence_pages, scan.cache.engine_tag,
    )


def _seed(scan, text: str, confidence: float) -> None:
    for number in scan.pages:
        scan.cache.path_for(scan.sha256, number).write_text(
            json.dumps({"text": text, "mean_confidence": confidence, "engine": PADDLE_ENGINE}),
            encoding="utf-8",
        )


def _extract(scan, threshold: float | None = THRESHOLD) -> PdfExtraction:
    return PdfExtractor(
        scan.path, source_sha256=scan.sha256, engine=NoEngine(),
        cache=scan.cache, fallback_threshold=threshold,
    ).extract()


def test_native_only_extraction_has_no_ocr_pages(low_confidence_scan) -> None:
    extraction = extract_pdf(low_confidence_scan.path)
    assert extraction.ocr_pages == ()
    assert not extraction.low_confidence


def test_low_confidence_pages_are_listed(low_confidence_scan) -> None:
    extraction = _extract(low_confidence_scan)
    assert list(extraction.low_confidence_pages) == low_confidence_scan.pages
    assert extraction.low_confidence


def test_page_at_threshold_is_not_flagged(low_confidence_scan) -> None:
    _seed(low_confidence_scan, "Clear words from a decent scan", THRESHOLD)
    assert _extract(low_confidence_scan).low_confidence_pages == ()


def test_page_with_little_text_is_not_flagged(low_confidence_scan) -> None:
    _seed(low_confidence_scan, "x", 0.1)
    assert _extract(low_confidence_scan).low_confidence_pages == ()


def test_no_threshold_means_no_flags(low_confidence_scan) -> None:
    assert _extract(low_confidence_scan, threshold=None).low_confidence_pages == ()


def test_ocr_requires_cache_and_hash(low_confidence_scan) -> None:
    with pytest.raises(ValueError, match="OCR requires"):
        PdfExtractor(low_confidence_scan.path, engine=NoEngine())

# --- Acceptance criteria -----------------------------------------------------


def test_low_confidence_fixture_appears_in_flagged_list(
    conn, low_confidence_scan: LowConfidenceScan
) -> None:
    update = _run(conn, low_confidence_scan)

    assert update.document_flagged
    flagged = list_flagged(conn)
    assert [(f.document_id, f.page_number) for f in flagged] == [
        (low_confidence_scan.document_id, number) for number in low_confidence_scan.pages
    ]
    assert flagged[0].title == "scanned.pdf"
    assert flagged[0].mean_confidence == pytest.approx(0.31)
    assert _document_flag(conn, low_confidence_scan.document_id) == 1


def test_flag_clears_on_manual_review(conn, low_confidence_scan: LowConfidenceScan) -> None:
    _run(conn, low_confidence_scan)

    cleared = mark_reviewed(
        conn, low_confidence_scan.document_id, note="checked against the scan"
    )

    assert cleared == len(low_confidence_scan.pages)
    assert list_flagged(conn) == []
    assert _document_flag(conn, low_confidence_scan.document_id) == 0

    # Running the stage again does not bring the flag back.
    assert not _run(conn, low_confidence_scan).document_flagged
    assert list_flagged(conn) == []


# --- Flagging rules ----------------------------------------------------------


def test_confident_pages_are_not_flagged(conn, document_id: int) -> None:
    update = record_ocr_pages(conn, document_id, [_page(1, 0.95), _page(2, 0.8)], [], TAG)

    assert update.pages_recorded == 2
    assert not update.document_flagged
    assert list_flagged(conn) == []
    assert _document_flag(conn, document_id) == 0


def test_one_low_page_flags_the_document(conn, document_id: int) -> None:
    record_ocr_pages(conn, document_id, [_page(1, 0.95), _page(2, 0.4)], [2], TAG)

    assert [f.page_number for f in list_flagged(conn)] == [2]
    assert _document_flag(conn, document_id) == 1


def test_engine_is_recorded_per_page(conn, document_id: int) -> None:
    record_ocr_pages(
        conn, document_id, [_page(1, 0.5, engine=TESSERACT_ENGINE)], [1], TAG
    )
    assert list_flagged(conn)[0].engine == TESSERACT_ENGINE


def test_pages_no_longer_ocrd_are_removed(conn, document_id: int) -> None:
    record_ocr_pages(conn, document_id, [_page(1, 0.4), _page(2, 0.4)], [1], TAG)
    record_ocr_pages(conn, document_id, [_page(1, 0.4)], [1], TAG)

    assert [f.page_number for f in list_flagged(conn)] == [1]


def test_unknown_document_rejected(conn) -> None:
    with pytest.raises(ValueError, match="No document"):
        record_ocr_pages(conn, 999, [_page(1, 0.4)], [1], TAG)


# --- Review ------------------------------------------------------------------


def test_review_keeps_recorded_confidence(conn, document_id: int) -> None:
    record_ocr_pages(conn, document_id, [_page(1, 0.4)], [1], TAG)
    mark_reviewed(conn, document_id, note="  names and dates checked  ")

    row = conn.execute(
        "SELECT mean_confidence, low_confidence, reviewed_at, review_note "
        "FROM document_page_ocr WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    assert row["mean_confidence"] == pytest.approx(0.4)
    assert row["low_confidence"] == 1
    assert row["reviewed_at"] is not None
    assert row["review_note"] == "names and dates checked"


def test_reviewing_again_clears_nothing(conn, document_id: int) -> None:
    record_ocr_pages(conn, document_id, [_page(1, 0.4)], [1], TAG)
    mark_reviewed(conn, document_id)
    assert mark_reviewed(conn, document_id) == 0


def test_new_ocr_setup_reflags_a_reviewed_page(conn, document_id: int) -> None:
    record_ocr_pages(conn, document_id, [_page(1, 0.4)], [1], TAG)
    mark_reviewed(conn, document_id)

    record_ocr_pages(conn, document_id, [_page(1, 0.45)], [1], NEW_TAG)

    assert [f.page_number for f in list_flagged(conn)] == [1]
    assert _document_flag(conn, document_id) == 1


def test_review_of_unknown_page_rejected(conn, document_id: int) -> None:
    record_ocr_pages(conn, document_id, [_page(1, 0.4)], [1], TAG)
    with pytest.raises(ValueError, match="page 7"):
        mark_reviewed(conn, document_id, page_number=7)


def test_review_of_unknown_document_rejected(conn) -> None:
    with pytest.raises(ValueError, match="No document"):
        mark_reviewed(conn, 999)