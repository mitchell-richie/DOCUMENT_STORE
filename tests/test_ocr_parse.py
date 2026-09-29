"""Unit tests for PaddleOCR output parsing (no models required)."""

import pytest

from document_store.ocr.paddle import OcrResult, parse_result


def test_parse_collects_texts_and_mean_confidence() -> None:
    results = [{"rec_texts": ["Hello", "World"], "rec_scores": [0.9, 0.8]}]
    result = parse_result(results)
    assert result.text == "Hello\nWorld"
    assert result.mean_confidence == pytest.approx(0.85)


def test_parse_handles_no_detections() -> None:
    assert parse_result([{"rec_texts": [], "rec_scores": []}]) == OcrResult(lines=[])


def test_parse_handles_none_lists() -> None:
    assert parse_result([{"rec_texts": None, "rec_scores": None}]).mean_confidence == 0.0


def test_parse_handles_multiple_images() -> None:
    results = [
        {"rec_texts": ["Page one"], "rec_scores": [0.9]},
        {"rec_texts": ["Page two"], "rec_scores": [0.7]},
    ]
    assert parse_result(results).text == "Page one\nPage two"


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError):
        parse_result([{"rec_texts": ["a", "b"], "rec_scores": [0.9]}])