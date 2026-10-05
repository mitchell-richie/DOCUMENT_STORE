"""OCR for image-only PDF pages and image files, with a per-page cache.

Results are cached by source SHA-256, page number, and engine tag, so
re-running ingestion does not repeat OCR work.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Protocol

import pymupdf

from document_store.ocr.paddle import OcrResult, run_ocr

log = logging.getLogger(__name__)

# Bump when the handling of OCR output changes in code, so cached results
# from the previous behaviour are not reused.
PIPELINE_VERSION = 1
DEFAULT_DPI = 200

class OcrEngine(Protocol):
    def predict(self, input: str) -> Any: ...


@dataclass(frozen=True)
class OcrPage:
    page_number: int  # 1-based
    text: str
    mean_confidence: float
    from_cache: bool = False


def engine_tag(dpi: int) -> str:
    """Identify the OCR setup that produced a result: engine version, render DPI,
    and pipeline version."""
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
            from_cache=True,
        )

    def store(self, source_sha256: str, page_number: int, result: OcrResult) -> None:
        path = self.path_for(source_sha256, page_number)
        payload = {"text": result.text, "mean_confidence": result.mean_confidence}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)


def _page(page_number: int, result: OcrResult) -> OcrPage:
    return OcrPage(
        page_number=page_number,
        text=result.text,
        mean_confidence=result.mean_confidence,
    )


def _ocr_pixmap(engine: OcrEngine, pixmap: pymupdf.Pixmap, work_dir: Path) -> OcrResult:
    """OCR a rendered page. The temporary PNG is removed afterwards."""
    work_dir.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(suffix=".png", dir=work_dir)
    os.close(descriptor)
    temporary = Path(name)
    try:
        pixmap.save(temporary)
        return run_ocr(engine, temporary)
    finally:
        temporary.unlink(missing_ok=True)


def ocr_pdf_pages(
    engine: OcrEngine,
    pdf_path: Path,
    source_sha256: str,
    page_numbers: Iterable[int],
    cache: OcrCache,
) -> list[OcrPage]:
    """OCR the given pages (1-based) of a PDF, using the cache where possible."""
    pages: list[OcrPage] = []
    with pymupdf.open(pdf_path) as doc:
        for number in page_numbers:
            cached = cache.load(source_sha256, number)
            if cached is not None:
                pages.append(cached)
                continue

            log.info("OCR page %d of %s", number, pdf_path.name)
            pixmap = doc[number - 1].get_pixmap(dpi=cache.dpi)
            result = _ocr_pixmap(engine, pixmap, cache.root)
            cache.store(source_sha256, number, result)
            pages.append(_page(number, result))
    return pages


def ocr_image(
    engine: OcrEngine,
    image_path: Path,
    source_sha256: str,
    cache: OcrCache,
) -> OcrPage:
    """OCR an image file as a single page (page 1), using the cache where possible."""
    cached = cache.load(source_sha256, 1)
    if cached is not None:
        return cached

    log.info("OCR image %s", image_path.name)
    result = run_ocr(engine, image_path)
    cache.store(source_sha256, 1, result)
    return _page(1, result)
