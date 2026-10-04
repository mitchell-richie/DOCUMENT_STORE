"""Tests for native PDF text extraction (STORY-3.1)."""

from pathlib import Path

import pymupdf
import pytest

from document_store.extract.pdf import ExtractionError, extract_pdf


def test_native_pdf_pages_are_numbered_from_one(fixtures_dir: Path) -> None:
    result = extract_pdf(fixtures_dir / "native.pdf")

    assert result.page_count == 2
    assert [p.page_number for p in result.pages] == [1, 2]
    assert "Synthetic native page 1." in result.pages[0].text
    assert "Synthetic native page 2." in result.pages[1].text


def test_native_pages_report_a_text_layer(fixtures_dir: Path) -> None:
    result = extract_pdf(fixtures_dir / "native.pdf")

    assert all(page.has_text_layer for page in result.pages)
    assert result.pages_without_text == []


def test_scanned_pdf_reports_no_text_layer(fixtures_dir: Path) -> None:
    result = extract_pdf(fixtures_dir / "scanned.pdf")

    assert result.page_count == 1
    assert result.pages[0].has_text_layer is False
    assert result.pages_without_text == [1]


def test_min_text_chars_threshold_applies(fixtures_dir: Path) -> None:
    result = extract_pdf(fixtures_dir / "native.pdf", min_text_chars=10**9)

    assert not any(page.has_text_layer for page in result.pages)


def test_encrypted_pdf_raises(tmp_path: Path, fixtures_dir: Path) -> None:
    target = tmp_path / "locked.pdf"
    with pymupdf.open(fixtures_dir / "native.pdf") as doc:
        doc.save(
            target,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )

    with pytest.raises(ExtractionError, match="encrypted"):
        extract_pdf(target)


def test_unreadable_file_raises(tmp_path: Path) -> None:
    target = tmp_path / "broken.pdf"
    target.write_bytes(b"this is not a pdf")

    with pytest.raises(ExtractionError, match="cannot open"):
        extract_pdf(target)