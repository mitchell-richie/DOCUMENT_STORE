"""OCR run over registered documents (STORY-3.9).

Runs the PDF and image extractors, with OCR enabled, for every registered
document whose route permits content processing, and records per-page
confidence and low-confidence flags. OCR text stays in the OCR cache; only
confidences and identifiers are written to the database.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from document_store.constants import CONTENT_ROUTES
from document_store.extract.base import DEFAULT_MIN_TEXT_CHARS
from document_store.extract.errors import ExtractionError
from document_store.extract.image import ImageExtractor
from document_store.extract.ocr import OcrCache, OcrEngine
from document_store.extract.pdf import PdfExtractor
from document_store.ingest.ocr_flags import FlagUpdate, record_ocr_pages
from document_store.ingest.register import sha256_of

log = logging.getLogger(__name__)

PDF_MIME_TYPE = "application/pdf"
IMAGE_MIME_PREFIX = "image/"

EXPECTED_ERRORS = (ExtractionError, OSError, ValueError, RuntimeError, sqlite3.Error)


@dataclass(frozen=True)
class OcrCandidate:
    document_id: int
    title: str
    source_file_id: int
    sha256: str
    mime_type: str


@dataclass
class OcrSummary:
    documents_processed: int = 0
    pages_ocrd: int = 0
    documents_flagged: int = 0
    pages_flagged: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Counts and failed file names, for the run log. No document content."""
        return {
            "documents_processed": self.documents_processed,
            "pages_ocrd": self.pages_ocrd,
            "documents_flagged": self.documents_flagged,
            "pages_flagged": self.pages_flagged,
            "files_failed": [title for title, _ in self.errors],
        }


def list_candidates(conn: sqlite3.Connection) -> list[OcrCandidate]:
    """Top-level PDF and image documents on a route that permits content processing."""
    routes = sorted(CONTENT_ROUTES)
    placeholders = ", ".join("?" for _ in routes)
    rows = conn.execute(
        "SELECT d.id AS document_id, d.title, s.id AS source_file_id, s.sha256, s.mime_type "
        "FROM document d JOIN source_file s ON s.id = d.source_file_id "
        f"WHERE d.parent_id IS NULL AND d.processing_route IN ({placeholders}) "
        "AND (s.mime_type = ? OR s.mime_type LIKE ?) "
        "ORDER BY d.id",
        (*routes, PDF_MIME_TYPE, IMAGE_MIME_PREFIX + "%"),
    ).fetchall()
    return [
        OcrCandidate(
            document_id=row["document_id"],
            title=row["title"] or f"document {row['document_id']}",
            source_file_id=row["source_file_id"],
            sha256=row["sha256"],
            mime_type=row["mime_type"],
        )
        for row in rows
    ]


def find_original(conn: sqlite3.Connection, candidate: OcrCandidate) -> Path | None:
    """Return a recorded location whose content still matches the registered hash."""
    rows = conn.execute(
        "SELECT path FROM source_file_location WHERE source_file_id = ? ORDER BY id",
        (candidate.source_file_id,),
    ).fetchall()
    for row in rows:
        path = Path(row["path"])
        if path.is_file() and sha256_of(path) == candidate.sha256:
            return path
    return None


def ocr_document(
    conn: sqlite3.Connection,
    engine: OcrEngine,
    cache: OcrCache,
    candidate: OcrCandidate,
    path: Path,
    threshold: float,
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
) -> FlagUpdate:
    """Extract one document with OCR and record its page confidences and flags."""
    if candidate.mime_type == PDF_MIME_TYPE:
        pdf = PdfExtractor(
            path,
            min_text_chars,
            source_sha256=candidate.sha256,
            engine=engine,
            cache=cache,
            fallback_threshold=threshold,
        ).extract()
        return record_ocr_pages(
            conn,
            candidate.document_id,
            pdf.ocr_pages,
            pdf.low_confidence_pages,
            cache.engine_tag,
        )

    image = ImageExtractor(
        path,
        source_sha256=candidate.sha256,
        engine=engine,
        cache=cache,
        fallback_threshold=threshold,
        min_text_chars=min_text_chars,
    ).extract()
    flagged = [image.page.page_number] if image.low_confidence else []
    return record_ocr_pages(
        conn, candidate.document_id, [image.page], flagged, cache.engine_tag
    )


def ocr_documents(
    conn: sqlite3.Connection,
    engine: OcrEngine,
    cache: OcrCache,
    threshold: float,
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
) -> OcrSummary:
    """OCR every candidate document. Per-document failures are recorded."""
    summary = OcrSummary()
    candidates = list_candidates(conn)
    for position, candidate in enumerate(candidates, start=1):
        log.info("OCR check %d of %d: %s", position, len(candidates), candidate.title)
        try:
            path = find_original(conn, candidate)
            if path is None:
                raise FileNotFoundError("no copy matching the registered hash was found")
            update = ocr_document(
                conn, engine, cache, candidate, path, threshold, min_text_chars
            )
        except EXPECTED_ERRORS as exc:
            log.error("failed to OCR %s: %s", candidate.title, exc)
            summary.errors.append((candidate.title, str(exc)))
            continue

        summary.documents_processed += 1
        summary.pages_ocrd += update.pages_recorded
        summary.pages_flagged += update.pages_awaiting_review
        if update.document_flagged:
            summary.documents_flagged += 1
    return summary