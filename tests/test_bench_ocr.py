"""Tests for the OCR benchmark harness (STORY-3.7), using fake engines."""

import shutil
from pathlib import Path

import pytest

from document_store.bench.ocr import (
    discover_items,
    render_markdown,
    run_benchmark,
)
from document_store.ocr.paddle import OcrLine, OcrResult

REFERENCE = "Synthetic Receipt Total 12.50 Date 01/05/2024"


def _result(text: str, confidence: float = 0.9) -> OcrResult:
    return OcrResult(lines=[OcrLine(text=text, confidence=confidence)])


@pytest.fixture
def dataset(tmp_path: Path, fixtures_dir: Path) -> Path:
    folder = tmp_path / "dataset"
    folder.mkdir()
    shutil.copy(fixtures_dir / "receipt.png", folder / "receipt_001.png")
    (folder / "receipt_001.txt").write_text(REFERENCE, encoding="utf-8")
    shutil.copy(fixtures_dir / "receipt.png", folder / "receipt_002.png")  # no transcript
    return folder


def test_discover_pairs_images_with_transcripts(dataset: Path) -> None:
    items, skipped = discover_items(dataset)

    assert [i.name for i in items] == ["receipt_001"]
    assert items[0].reference == REFERENCE
    assert skipped == ["receipt_002.png"]


def test_perfect_engine_scores_zero_and_weak_engine_scores_higher(dataset: Path) -> None:
    items, _ = discover_items(dataset)
    engines = {
        "perfect": lambda path: _result(REFERENCE),
        "weak": lambda path: _result("Synthetic"),
    }

    _, summaries = run_benchmark(items, engines)
    by_name = {s.engine: s for s in summaries}

    assert by_name["perfect"].mean_cer == 0.0
    assert by_name["weak"].mean_cer > 0.0
    assert by_name["perfect"].items == 1


def test_results_are_recorded_per_item_and_engine(dataset: Path) -> None:
    items, _ = discover_items(dataset)
    engines = {"a": lambda path: _result(REFERENCE), "b": lambda path: _result("")}

    results, _ = run_benchmark(items, engines)

    assert sorted((r.item, r.engine) for r in results) == [
        ("receipt_001", "a"),
        ("receipt_001", "b"),
    ]


def test_markdown_lists_each_engine(dataset: Path) -> None:
    items, _ = discover_items(dataset)
    _, summaries = run_benchmark(items, {"perfect": lambda path: _result(REFERENCE)})

    markdown = render_markdown(summaries, {"paddleocr": "3.7.0"})

    assert "| perfect |" in markdown
    assert "paddleocr 3.7.0" in markdown