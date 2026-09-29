"""Integration test: PaddleOCR reads a rendered sample image."""

from pathlib import Path

import pytest

from document_store.ocr.check import run_check

pytestmark = pytest.mark.ocr


def test_sample_image_is_recognised(tmp_path: Path) -> None:
    report = run_check(tmp_path, use_gpu=False)
    assert report.device == "cpu"
    assert "12345" in report.text
    assert report.mean_confidence > 0
    assert report.passed