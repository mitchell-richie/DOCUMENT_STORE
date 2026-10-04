"""Native PDF text extraction.

Reads the embedded text layer of each page. Pages with no text layer are
reported with has_text_layer=False; OCR for those pages is handled by the
OCR route (STORY-3.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf


class ExtractionError(Exception):
    """Raised when a file cannot be read as an unencrypted PDF.

    The message names the file but never includes document text.
    """


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-based
    text: str
    has_text_layer: bool


@dataclass(frozen=True)
class PdfExtraction:
    pages: tuple[PageText, ...]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def pages_without_text(self) -> list[int]:
        """Page numbers with no usable text layer (candidates for OCR)."""
        return [page.page_number for page in self.pages if not page.has_text_layer]


def extract_pdf(path: Path, min_text_chars: int = 1) -> PdfExtraction:
    """Extract text from each page of a PDF.

    Args:
        path: the PDF file.
        min_text_chars: a page is considered to have a text layer when its
            non-whitespace text is at least this long.

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
            )
            for index, page in enumerate(doc, start=1)
            for text in [page.get_text("text")]
        )
    return PdfExtraction(pages=pages)