"""Tesseract fallback OCR.

Used only when PaddleOCR's confidence is below the configured threshold
(see extract/ocr.py). Tesseract reports word-level output, so words are
grouped into lines to match PaddleOCR's output shape.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from document_store.ocr.paddle import OcrLine, OcrResult

TESSERACT_ENGINE = "tesseract"


def parse_tesseract_data(data: Mapping[str, Sequence[Any]]) -> OcrResult:
    """Convert pytesseract.image_to_data(DICT) output into an OcrResult.

    Words with no text, or confidence -1 (non-word rows), are ignored.
    Tesseract confidences are 0-100; they are scaled to 0-1.
    """
    groups: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
    for text, conf, block, par, line in zip(
        data["text"],
        data["conf"],
        data["block_num"],
        data["par_num"],
        data["line_num"],
        strict=True,
    ):
        confidence = float(conf)
        if not str(text).strip() or confidence < 0:
            continue
        groups.setdefault((int(block), int(par), int(line)), []).append(
            (str(text), confidence)
        )

    lines = [
        OcrLine(
            text=" ".join(word for word, _ in words),
            confidence=sum(conf for _, conf in words) / len(words) / 100.0,
        )
        for words in groups.values()
    ]
    return OcrResult(lines=lines)


def tesseract_ocr(image_path: Path) -> OcrResult:
    """Run Tesseract on an image file.

    Raises:
        OSError: if the Tesseract binary is not installed.
        RuntimeError: if Tesseract fails.
    """
    import pytesseract
    from PIL import Image

    with Image.open(image_path) as image:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    return parse_tesseract_data(data)