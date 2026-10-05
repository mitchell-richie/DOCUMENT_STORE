"""Native PDF text extraction.

Reads the embedded text layer of each page. Pages with no text layer are
reported with has_text_layer=False; OCR for those pages is handled by the
OCR route (STORY-3.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

DEFAULT_MIN_TEXT_CHARS = 20


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


def extract_pdf(path: Path, min_text_chars: int = DEFAULT_MIN_TEXT_CHARS) -> PdfExtraction:
    """Extract text from each page of a PDF.

    Args:
        path: the PDF file.
        min_text_chars: a page has a text layer when its non-whitespace text is
            at least this long.

    Raises:
        ExtractionError: if the file cannot be opened as a PDF, or is encrypted.
    """
    try:
        doc = pymupdf.open(path)
    except RuntimeError as exc:
        raise ExtractionError(f"cannot open PDF: {path.name}") from exc

    with doc:
        if doc.needs_pass:
            raise ExtractionError(f"encrypted PDF: {path.name}")
        pages = tuple(
            PageText(
                page_number=index,
                text=text,
                has_text_layer=len(text.strip()) >= min_text_chars,
                has_images=bool(page.get_images()),
            )
            for index, page in enumerate(doc, start=1)
            for text in [page.get_text("text")]
        )
    return PdfExtraction(pages=pages)

    
class ExtractionError(Exception):
    """Raised when a file cannot be read as an unencrypted PDF.

    The message names the file but never includes document text.
    """
