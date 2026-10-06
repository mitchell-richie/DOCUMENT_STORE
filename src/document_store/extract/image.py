"""Standalone image extraction (STORY-3.8).

An image is OCR'd as a single page. If the OCR text is shorter than
min_text_chars, the image is flagged needs_vision=True: it probably contains no
text worth indexing (a photograph, for example). Describing such images with a
vision model is deferred to EPIC-6.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from document_store.extract.base import DEFAULT_MIN_TEXT_CHARS, Extractor
from document_store.extract.errors import ExtractionError
from document_store.extract.ocr import OcrCache, OcrEngine, OcrPage, ocr_image


@dataclass(frozen=True)
class ImageExtraction:
    page: OcrPage
    needs_vision: bool


class ImageExtractor(Extractor[ImageExtraction]):
    format_name = "image"
    # Pillow raises UnidentifiedImageError (a subclass of OSError) for non-images.
    open_errors = (OSError,)

    def __init__(
        self,
        path: Path,
        *,
        source_sha256: str,
        engine: OcrEngine,
        cache: OcrCache,
        fallback_threshold: float | None = None,
        min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
    ) -> None:
        super().__init__(path)
        self.source_sha256 = source_sha256
        self.engine = engine
        self.cache = cache
        self.fallback_threshold = fallback_threshold
        self.min_text_chars = min_text_chars

    def _open(self) -> Image.Image:
        return Image.open(self.path)

    def _check(self, source: Image.Image) -> None:
        # Opening is lazy; verify() reads the image data and catches corruption.
        try:
            source.verify()
        except (OSError, SyntaxError, ValueError) as exc:
            raise ExtractionError(f"cannot open image: {self.path.name}") from exc

    def _read(self, source: Image.Image) -> ImageExtraction:
        page = ocr_image(
            self.engine,
            self.path,
            self.source_sha256,
            self.cache,
            self.fallback_threshold,
        )
        return ImageExtraction(
            page=page,
            needs_vision=len(page.text.strip()) < self.min_text_chars,
        )

    def _close(self, source: Image.Image) -> None:
        source.close()


def extract_image(
    path: Path,
    *,
    source_sha256: str,
    engine: OcrEngine,
    cache: OcrCache,
    fallback_threshold: float | None = None,
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
) -> ImageExtraction:
    """OCR an image and flag it if it contains no meaningful text.

    Raises:
        ExtractionError: if the file cannot be read as an image.
    """
    return ImageExtractor(
        path,
        source_sha256=source_sha256,
        engine=engine,
        cache=cache,
        fallback_threshold=fallback_threshold,
        min_text_chars=min_text_chars,
    ).extract()