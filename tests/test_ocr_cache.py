"""Tests for the OCR cache and page routing (STORY-3.3), using a fake engine."""

from pathlib import Path

import pytest

from document_store.extract.ocr import OcrCache, engine_tag, ocr_image, ocr_pdf_pages


class FakeEngine:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, input: str):
        self.calls += 1
        return [{"rec_texts": ["Fake text"], "rec_scores": [0.9]}]


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def cache(tmp_path: Path) -> OcrCache:
    return OcrCache(tmp_path / "cache")


def test_pdf_pages_return_text_and_confidence(
    engine: FakeEngine, cache: OcrCache, fixtures_dir: Path
) -> None:
    pages = ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-a", [1], cache)

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert pages[0].text == "Fake text"
    assert pages[0].mean_confidence == pytest.approx(0.9)
    assert pages[0].from_cache is False


def test_second_run_uses_cache(engine: FakeEngine, cache: OcrCache, fixtures_dir: Path) -> None:
    ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-a", [1], cache)
    pages = ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-a", [1], cache)

    assert engine.calls == 1
    assert pages[0].from_cache is True


def test_different_source_hash_is_not_cached_together(
    engine: FakeEngine, cache: OcrCache, fixtures_dir: Path
) -> None:
    ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-a", [1], cache)
    ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-b", [1], cache)

    assert engine.calls == 2


def test_output_is_stored_per_page(
    engine: FakeEngine, cache: OcrCache, fixtures_dir: Path
) -> None:
    ocr_pdf_pages(engine, fixtures_dir / "native.pdf", "sha-a", [1, 2], cache)

    stored = sorted(p.name for p in cache.root.glob("*.json"))
    assert stored == [
        f"sha-a-p0001-{cache.engine_tag}.json",
        f"sha-a-p0002-{cache.engine_tag}.json",
    ]


def test_temporary_images_are_removed(
    engine: FakeEngine, cache: OcrCache, fixtures_dir: Path
) -> None:
    ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-a", [1], cache)

    assert list(cache.root.glob("*.png")) == []


def test_image_file_is_ocr_d_as_page_one(
    engine: FakeEngine, cache: OcrCache, fixtures_dir: Path
) -> None:
    page = ocr_image(engine, fixtures_dir / "receipt.png", "sha-img", cache)
    again = ocr_image(engine, fixtures_dir / "receipt.png", "sha-img", cache)

    assert page.page_number == 1
    assert page.text == "Fake text"
    assert again.from_cache is True
    assert engine.calls == 1


def test_dpi_change_invalidates_cache(engine: FakeEngine, tmp_path: Path, fixtures_dir: Path) -> None:
    ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-a", [1], OcrCache(tmp_path / "c", dpi=200))
    ocr_pdf_pages(engine, fixtures_dir / "scanned.pdf", "sha-a", [1], OcrCache(tmp_path / "c", dpi=300))

    assert engine.calls == 2


def test_engine_tag_records_dpi_and_version() -> None:
    tag = engine_tag(300)
    assert "dpi300" in tag
    assert "pipeline" in tag