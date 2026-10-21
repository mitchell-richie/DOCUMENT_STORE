"""OCR for image-only PDF pages and image files.

Provides a per-page cache, and a Tesseract fallback for results whose
confidence is below a threshold (STORY-3.3, STORY-3.5).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Protocol

import pymupdf

from document_store.ocr.paddle import OcrResult, run_ocr
from document_store.ocr.tesseract import TESSERACT_ENGINE, tesseract_ocr

log = logging.getLogger(__name__)

PADDLE_ENGINE = "paddleocr"
DEFAULT_DPI = 200
# Bump when the handling of OCR output changes in code, so cached results
# from the previous behaviour are not reused.
PIPELINE_VERSION = 3

FallbackRunner = Callable[[], OcrResult]


class OcrEngine(Protocol):
    def predict(self, input: str) -> Any: ...


@dataclass(frozen=True)
class OcrPage:
    page_number: int  # 1-based
    text: str
    mean_confidence: float
    engine: str = PADDLE_ENGINE
    from_cache: bool = False

    def is_low_confidence(self, threshold: float, min_text_chars: int) -> bool:
        """True if the page has meaningful text and its confidence is below threshold.

        A page with fewer than min_text_chars of recognised text is not
        low-confidence text; it probably contains no text at all (a
        photograph or a blank scan) and is handled by the vision route.
        """
        return len(self.text.strip()) >= min_text_chars and self.mean_confidence < threshold


def engine_tag(dpi: int) -> str:
    """Identify the OCR setup that produced a result: engine version, render
    DPI, and pipeline version."""
    return f"paddleocr{package_version('paddleocr')}-dpi{dpi}-pipeline{PIPELINE_VERSION}"


class OcrCache:
    """File-based cache of OCR output, one JSON file per page.

    The cache records the DPI it was built for, so results at one resolution
    are never returned for another.
    """

    def __init__(self, root: Path, dpi: int = DEFAULT_DPI) -> None:
        self.root = root
        self.dpi = dpi
        self.engine_tag = engine_tag(dpi)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, source_sha256: str, page_number: int) -> Path:
        return self.root / f"{source_sha256}-p{page_number:04d}-{self.engine_tag}.json"

    def load(self, source_sha256: str, page_number: int) -> OcrPage | None:
        path = self.path_for(source_sha256, page_number)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return OcrPage(
            page_number=page_number,
            text=data["text"],
            mean_confidence=float(data["mean_confidence"]),
            engine=data.get("engine", PADDLE_ENGINE),
            from_cache=True,
        )

    def store(
        self,
        source_sha256: str,
        page_number: int,
        result: OcrResult,
        engine: str,
    ) -> None:
        path = self.path_for(source_sha256, page_number)
        payload = {
            "text": result.text,
            "mean_confidence": result.mean_confidence,
            "engine": engine,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)


def choose_result(
    primary: OcrResult,
    fallback: FallbackRunner | None,
    threshold: float | None,
) -> tuple[OcrResult, str]:
    """Return the best OCR result and the engine that produced it.

    The fallback runs only when the primary mean confidence is below the
    threshold. Its result is used only if it is more confident than the
    primary. If the fallback is unavailable or fails, the primary is kept.
    """
    if threshold is None or fallback is None or primary.mean_confidence >= threshold:
        return primary, PADDLE_ENGINE

    try:
        alternative = fallback()
    except (OSError, RuntimeError) as exc:
        log.warning("fallback OCR unavailable, keeping primary result: %s", exc)
        return primary, PADDLE_ENGINE

    if alternative.mean_confidence > primary.mean_confidence:
        return alternative, TESSERACT_ENGINE
    return primary, PADDLE_ENGINE


def _ocr_pixmap(
    engine: OcrEngine,
    pixmap: pymupdf.Pixmap,
    work_dir: Path,
    fallback_threshold: float | None,
) -> tuple[OcrResult, str]:
    """OCR a rendered page. The temporary PNG is removed afterwards."""
    work_dir.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(suffix=".png", dir=work_dir)
    os.close(descriptor)
    temporary = Path(name)
    try:
        pixmap.save(temporary)
        primary = run_ocr(engine, temporary)
        return choose_result(primary, lambda: tesseract_ocr(temporary), fallback_threshold)
    finally:
        temporary.unlink(missing_ok=True)


def ocr_pdf_pages(
    engine: OcrEngine,
    pdf_path: Path,
    source_sha256: str,
    page_numbers: Iterable[int],
    cache: OcrCache,
    fallback_threshold: float | None = None,
) -> list[OcrPage]:
    """OCR the given pages (1-based) of a PDF, using the cache where possible.

    Pass fallback_threshold (normally ocr_confidence_threshold) to enable the
    Tesseract fallback; None disables it.
    """
    pages: list[OcrPage] = []
    with pymupdf.open(pdf_path) as doc:
        for number in page_numbers:
            cached = cache.load(source_sha256, number)
            if cached is not None:
                pages.append(cached)
                continue

            log.info("OCR page %d of %s", number, pdf_path.name)
            pixmap = doc[number - 1].get_pixmap(dpi=cache.dpi)
            result, used = _ocr_pixmap(engine, pixmap, cache.root, fallback_threshold)
            cache.store(source_sha256, number, result, used)
            pages.append(
                OcrPage(
                    page_number=number,
                    text=result.text,
                    mean_confidence=result.mean_confidence,
                    engine=used,
                )
            )
    return pages


def ocr_image(
    engine: OcrEngine,
    image_path: Path,
    source_sha256: str,
    cache: OcrCache,
    fallback_threshold: float | None = None,
) -> OcrPage:
    """OCR an image file as a single page (page 1), using the cache where possible."""
    cached = cache.load(source_sha256, 1)
    if cached is not None:
        return cached

    log.info("OCR image %s", image_path.name)
    primary = run_ocr(engine, image_path)
    result, used = choose_result(
        primary, lambda: tesseract_ocr(image_path), fallback_threshold
    )
    cache.store(source_sha256, 1, result, used)
    return OcrPage(
        page_number=1,
        text=result.text,
        mean_confidence=result.mean_confidence,
        engine=used,
    )