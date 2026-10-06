"""Tests for standalone image extraction (STORY-3.8), using a fake engine."""

from pathlib import Path

import pytest

from document_store.extract.errors import ExtractionError
from document_store.extract.image import extract_image
from document_store.extract.ocr import OcrCache


class FakeEngine:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def predict(self, input: str):
        self.calls += 1
        return [{"rec_texts": [self.text], "rec_scores": [0.9]}]


@pytest.fixture
def cache(tmp_path: Path) -> OcrCache:
    return OcrCache(tmp_path / "cache")


def test_receipt_text_is_extracted(fixtures_dir: Path, cache: OcrCache) -> None:
    engine = FakeEngine("Synthetic Receipt Total 12.50 Date 01/05/2024")

    result = extract_image(
        fixtures_dir / "receipt.png", source_sha256="sha-r", engine=engine, cache=cache
    )

    assert result.page.page_number == 1
    assert "Total 12.50" in result.page.text
    assert result.page.engine == "paddleocr"
    assert result.needs_vision is False


def test_image_without_meaningful_text_is_flagged(fixtures_dir: Path, cache: OcrCache) -> None:
    result = extract_image(
        fixtures_dir / "receipt.png",
        source_sha256="sha-r",
        engine=FakeEngine("ok"),
        cache=cache,
    )

    assert result.needs_vision is True


def test_whitespace_only_text_is_flagged(fixtures_dir: Path, cache: OcrCache) -> None:
    result = extract_image(
        fixtures_dir / "receipt.png",
        source_sha256="sha-r",
        engine=FakeEngine("   "),
        cache=cache,
    )

    assert result.needs_vision is True


def test_min_text_chars_controls_the_flag(fixtures_dir: Path, cache: OcrCache) -> None:
    result = extract_image(
        fixtures_dir / "receipt.png",
        source_sha256="sha-r",
        engine=FakeEngine("ok"),
        cache=cache,
        min_text_chars=2,
    )

    assert result.needs_vision is False


def test_second_extraction_uses_cache(fixtures_dir: Path, cache: OcrCache) -> None:
    engine = FakeEngine("Synthetic Receipt Total 12.50")

    extract_image(fixtures_dir / "receipt.png", source_sha256="sha-r", engine=engine, cache=cache)
    second = extract_image(
        fixtures_dir / "receipt.png", source_sha256="sha-r", engine=engine, cache=cache
    )

    assert engine.calls == 1
    assert second.page.from_cache is True


def test_unreadable_image_raises(tmp_path: Path, cache: OcrCache) -> None:
    target = tmp_path / "broken.png"
    target.write_bytes(b"not an image")

    with pytest.raises(ExtractionError, match="cannot open image"):
        extract_image(target, source_sha256="sha-x", engine=FakeEngine("x"), cache=cache)