"""PaddleOCR 3.x wrapper.

Converts PaddleOCR output into plain data classes so that the rest of the
pipeline does not depend on PaddleOCR's result objects.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float


@dataclass(frozen=True)
class OcrResult:
    lines: list[OcrLine]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_confidence(self) -> float:
        if not self.lines:
            return 0.0
        return sum(line.confidence for line in self.lines) / len(self.lines)


def parse_result(results: Iterable[Mapping[str, Any]]) -> OcrResult:
    """Convert PaddleOCR 3.x predict() output into an OcrResult.

    Each result describes one input image and carries parallel lists
    'rec_texts' and 'rec_scores'.
    """
    lines: list[OcrLine] = []
    for res in results:
        texts = res["rec_texts"] or []
        scores = res["rec_scores"] or []
        lines.extend(
            OcrLine(text=str(text), confidence=float(score))
            for text, score in zip(texts, scores, strict=True)
        )
    return OcrResult(lines=lines)


def create_engine(use_gpu: bool = False, enable_mkldnn: bool = False) -> Any:
    """Create a PaddleOCR engine. The first call may download model files.

    enable_mkldnn defaults to False: PaddlePaddle 3.3.1's oneDNN execution
    path raises NotImplementedError on PP-OCRv6 detection for certain inputs
    (ConvertPirAttribute2RuntimeAttribute). Revisit once this is fixed
    upstream, since oneDNN otherwise speeds up CPU inference noticeably.

    Document preprocessing models are disabled: they suit photographed
    pages but add latency, and the scans in this corpus are mostly flat.
    Revisit if OCR quality on skewed scans is poor (STORY-3.4).
    """
    from paddleocr import PaddleOCR

    kwargs: dict[str, Any] = {
        "lang": "en",
        "device": "gpu:0" if use_gpu else "cpu",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    if not use_gpu:
        kwargs["enable_mkldnn"] = enable_mkldnn

    return PaddleOCR(**kwargs)


def run_ocr(engine: Any, image_path: Path) -> OcrResult:
    """Run OCR on an image file."""
    return parse_result(engine.predict(str(image_path)))