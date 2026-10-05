"""Tests for the Tesseract fallback (STORY-3.5)."""

from pathlib import Path

import pytest

from document_store.extract import ocr as ocr_module
from document_store.extract.ocr import OcrCache, choose_result, ocr_pdf_pages
from document_store.ocr.paddle import OcrLine, OcrResult
from document_store.ocr.tesseract import TESSERACT_ENGINE, parse_tesseract_data


def _result(confidence: float, text: str = "text") -> OcrResult:
    return OcrResult(lines=[OcrLine(text=text, confidence=confidence)])


class CountingRunner:
    def __init__(self, value: OcrResult | None = None, error: Exception | None = None) -> None:
        self.calls = 0
        self.value = value
        self.error = error

    def __call__(self) -> OcrResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.value is not None
        return self.value


def test_high_confidence_does_not_call_fallback() -> None:
    runner = CountingRunner(_result(0.1))
    result, engine = choose_result(_result(0.9), runner, threshold=0.6)

    assert runner.calls == 0
    assert engine == "paddleocr"
    assert result.mean_confidence == pytest.approx(0.9)


def test_low_confidence_uses_more_confident_fallback() -> None:
    runner = CountingRunner(_result(0.8, "better"))
    result, engine = choose_result(_result(0.3, "worse"), runner, threshold=0.6)

    assert runner.calls == 1
    assert engine == TESSERACT_ENGINE
    assert result.text == "better"


def test_low_confidence_keeps_primary_if_fallback_is_worse() -> None:
    runner = CountingRunner(_result(0.2, "worse still"))
    result, engine = choose_result(_result(0.4, "primary"), runner, threshold=0.6)

    assert engine == "paddleocr"
    assert result.text == "primary"


def test_fallback_error_keeps_primary() -> None:
    runner = CountingRunner(error=OSError("tesseract not installed"))
    result, engine = choose_result(_result(0.3, "primary"), runner, threshold=0.6)

    assert engine == "paddleocr"
    assert result.text == "primary"


def test_no_threshold_disables_fallback() -> None:
    runner = CountingRunner(_result(0.9))
    choose_result(_result(0.1), runner, threshold=None)

    assert runner.calls == 0


def test_pdf_pages_record_engine_used(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class WeakEngine:
        def predict(self, input: str):
            return [{"rec_texts": ["weak"], "rec_scores": [0.2]}]

    monkeypatch.setattr(
        ocr_module, "tesseract_ocr", lambda path: _result(0.95, "strong")
    )
    pages = ocr_pdf_pages(
        WeakEngine(),
        fixtures_dir / "scanned.pdf",
        "sha-fb",
        [1],
        OcrCache(tmp_path / "cache"),
        fallback_threshold=0.6,
    )

    assert pages[0].text == "strong"
    assert pages[0].engine == TESSERACT_ENGINE


def test_parse_tesseract_groups_words_into_lines() -> None:
    data = {
        "text": ["Total", "12.50", "", "Date"],
        "conf": ["90", "80", "-1", "70"],
        "block_num": [1, 1, 1, 1],
        "par_num": [1, 1, 1, 1],
        "line_num": [1, 1, 1, 2],
    }
    result = parse_tesseract_data(data)

    assert [line.text for line in result.lines] == ["Total 12.50", "Date"]
    assert result.lines[0].confidence == pytest.approx(0.85)
    assert result.lines[1].confidence == pytest.approx(0.70)