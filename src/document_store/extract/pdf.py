"""Native PDF text extraction.

Reads the embedded text layer of each page. Pages with no text layer are
reported with has_text_layer=False; OCR for those pages is handled by the
OCR route (STORY-3.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from document_store.extract.base import DEFAULT_MIN_TEXT_CHARS, Extractor
from document_store.extract.errors import ExtractionError

__all__ = [
    "DEFAULT_MIN_TEXT_CHARS",
    "ExtractionError",
    "PageText",
    "PdfExtraction",
    "PdfExtractor",
    "extract_pdf",
]


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-based
    text: str
    has_text_layer: bool
    has_images: bool


@dataclass(frozen=True)
class PdfExtraction:
    pages: tuple[PageText, ...]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def pages_without_text(self) -> list[int]:
        """Page numbers with no usable text layer (blank or image-only)."""
        return [page.page_number for page in self.pages if not page.has_text_layer]

    @property
    def pages_needing_ocr(self) -> list[int]:
        """Page numbers with no usable text layer but at least one image.

        Blank pages (no text and no images) are excluded: OCR would find nothing.
        """
        return [
            page.page_number
            for page in self.pages
            if not page.has_text_layer and page.has_images
        ]


class PdfExtractor(Extractor[PdfExtraction]):
    format_name = "PDF"
    open_errors = (RuntimeError,)

    def __init__(self, path: Path, min_text_chars: int = DEFAULT_MIN_TEXT_CHARS) -> None:
        super().__init__(path)
        self.min_text_chars = min_text_chars

    def _open(self) -> pymupdf.Document:
        return pymupdf.open(self.path)

    def _check(self, source: pymupdf.Document) -> None:
        if source.needs_pass:
            raise ExtractionError(f"encrypted PDF: {self.path.name}")

    def _read(self, source: pymupdf.Document) -> PdfExtraction:
        pages = tuple(
            PageText(
                page_number=index,
                text=text,
                has_text_layer=len(text.strip()) >= self.min_text_chars,
                has_images=bool(page.get_images()),
            )
            for index, page in enumerate(source, start=1)
            for text in [page.get_text("text")]
        )
        return PdfExtraction(pages=pages)

    def _close(self, source: pymupdf.Document) -> None:
        source.close()


def extract_pdf(path: Path, min_text_chars: int = DEFAULT_MIN_TEXT_CHARS) -> PdfExtraction:
    """Extract text from each page of a PDF.

    Raises:
        ExtractionError: if the file cannot be opened as a PDF, or is encrypted.
    """
    return PdfExtractor(path, min_text_chars).extract()