"""Tests for recording and reviewing low-confidence OCR flags (STORY-3.9)."""

import sqlite3
from pathlib import Path

import pytest

from conftest import LowConfidenceScan, NoEngine
from document_store.extract.ocr import PADDLE_ENGINE, OcrPage
from document_store.extract.pdf import PdfExtractor
from document_store.ingest.documents import create_or_update_document
from document_store.ingest.ocr_flags import (
    FlagUpdate,
    list_flagged,
    mark_reviewed,
    record_ocr_pages,
)
from document_store.ingest.register import register_file
from document_store.ocr.tesseract import TESSERACT_ENGINE

THRESHOLD = 0.6
TAG = "paddleocr-test-dpi200"
NEW_TAG = "paddleocr-test-dpi300"


@pytest.fixture
def document_id(conn: sqlite3.Connection, fixtures_dir: Path) -> int:
    source = register_file(conn, fixtures_dir / "scanned.pdf").source_file_id
    return create_or_update_document(
        conn, source, "correspondence", "standard", "scanned.pdf"
    ).document_id


def _page(number: int, confidence: float, engine: str = PADDLE_ENGINE) -> OcrPage:
    return OcrPage(page_number=number, text="", mean_confidence=confidence, engine=engine)


def _document_flag(conn: sqlite3.Connection, document_id: int) -> int:
    return conn.execute(
        "SELECT low_confidence FROM document WHERE id = ?", (document_id,)
    ).fetchone()["low_confidence"]


def _run(conn: sqlite3.Connection, scan: LowConfidenceScan) -> FlagUpdate:
    extraction = PdfExtractor(
        scan.path,
        source_sha256=scan.sha256,
        engine=NoEngine(),
        cache=scan.cache,
        fallback_threshold=THRESHOLD,
    ).extract()
    return record_ocr_pages(
        conn,
        scan.document_id,
        extraction.ocr_pages,
        extraction.low_confidence_pages,
        scan.cache.engine_tag,
    )


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

    # Running OCR again does not bring the flag back.
    assert not _run(conn, low_confidence_scan).document_flagged
    assert list_flagged(conn) == []


# --- Recording ---------------------------------------------------------------


def test_unflagged_pages_leave_the_document_clear(conn, document_id: int) -> None:
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
    record_ocr_pages(conn, document_id, [_page(1, 0.5, engine=TESSERACT_ENGINE)], [1], TAG)
    assert list_flagged(conn)[0].engine == TESSERACT_ENGINE


def test_flag_is_reevaluated_on_rerun(conn, document_id: int) -> None:
    record_ocr_pages(conn, document_id, [_page(1, 0.7)], [], TAG)
    assert _document_flag(conn, document_id) == 0

    # The same result judged against a higher threshold.
    record_ocr_pages(conn, document_id, [_page(1, 0.7)], [1], TAG)
    assert _document_flag(conn, document_id) == 1


def test_pages_no_longer_ocrd_are_removed(conn, document_id: int) -> None:
    record_ocr_pages(conn, document_id, [_page(1, 0.4), _page(2, 0.4)], [1, 2], TAG)
    record_ocr_pages(conn, document_id, [_page(1, 0.4)], [1], TAG)

    assert [f.page_number for f in list_flagged(conn)] == [1]


def test_unknown_document_rejected(conn) -> None:
    with pytest.raises(ValueError, match="No document"):
        record_ocr_pages(conn, 999, [_page(1, 0.4)], [1], TAG)


# --- Review ------------------------------------------------------------------


def test_document_stays_flagged_until_every_page_is_reviewed(conn, document_id: int) -> None:
    record_ocr_pages(conn, document_id, [_page(1, 0.4), _page(2, 0.3)], [1, 2], TAG)

    assert mark_reviewed(conn, document_id, page_number=1) == 1
    assert [f.page_number for f in list_flagged(conn)] == [2]
    assert _document_flag(conn, document_id) == 1

    assert mark_reviewed(conn, document_id, page_number=2) == 1
    assert _document_flag(conn, document_id) == 0


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