"""Low-confidence OCR flags (STORY-3.9).

Records the OCR confidence of each page and flags pages below the threshold
for review. document.low_confidence is derived: it is set while any page of
the document is low-confidence and has not been reviewed.

This module stores confidences and identifiers only, never OCR text.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

log = logging.getLogger(__name__)


class OcrPageResult(Protocol):
    """The parts of an OCR result needed for recording (satisfied by OcrPage)."""

    @property
    def page_number(self) -> int: ...

    @property
    def mean_confidence(self) -> float: ...

    @property
    def engine(self) -> str: ...



@dataclass(frozen=True)
class FlagUpdate:
    pages_recorded: int
    pages_awaiting_review: int

    @property
    def document_flagged(self) -> bool:
        return self.pages_awaiting_review > 0


@dataclass(frozen=True)
class FlaggedPage:
    document_id: int
    title: str
    page_number: int
    engine: str
    mean_confidence: float


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _require_document(conn: sqlite3.Connection, document_id: int) -> None:
    row = conn.execute("SELECT 1 FROM document WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise ValueError(f"No document with id {document_id}")


def _refresh_document_flag(conn: sqlite3.Connection, document_id: int) -> int:
    """Set document.low_confidence from its pages. Returns pages awaiting review."""
    awaiting: int = conn.execute(
        "SELECT COUNT(*) FROM document_page_ocr "
        "WHERE document_id = ? AND low_confidence = 1 AND reviewed_at IS NULL",
        (document_id,),
    ).fetchone()[0]
    conn.execute(
        "UPDATE document SET low_confidence = ? WHERE id = ?",
        (int(awaiting > 0), document_id),
    )
    return awaiting


def record_ocr_pages(
    conn: sqlite3.Connection,
    document_id: int,
    pages: Iterable[OcrPageResult],
    low_confidence_pages: Collection[int],
    engine_tag: str,
    now: str | None = None,
) -> FlagUpdate:
    """Record the OCR result of every OCR'd page of a document and flag it.

    `pages` is the complete set of OCR'd pages for the document. Records for
    pages no longer in the set are removed.

    A page already recorded with the same engine and engine tag keeps its
    review state, so a cleared flag stays cleared on re-runs. Its flag is
    re-evaluated against the current threshold. A page produced by a
    different engine or engine tag is a new result: it replaces the record
    and any earlier review no longer applies.

    Raises:
        ValueError: if the document does not exist.
    """
    timestamp = now or _now()
    results = list(pages)
    flagged = set(low_confidence_pages)
    with conn:
        _require_document(conn, document_id)
        existing = {
            row["page_number"]: row
            for row in conn.execute(
                "SELECT page_number, engine, engine_tag FROM document_page_ocr "
                "WHERE document_id = ?",
                (document_id,),
            )
        }
        for page in results:
            low = int(page.page_number in flagged)
            previous = existing.pop(page.page_number, None)
            if previous is None:
                conn.execute(
                    "INSERT INTO document_page_ocr "
                    "(document_id, page_number, engine, engine_tag, mean_confidence, "
                    " low_confidence, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        document_id,
                        page.page_number,
                        page.engine,
                        engine_tag,
                        page.mean_confidence,
                        low,
                        timestamp,
                    ),
                )
            elif previous["engine"] == page.engine and previous["engine_tag"] == engine_tag:
                conn.execute(
                    "UPDATE document_page_ocr SET mean_confidence = ?, low_confidence = ? "
                    "WHERE document_id = ? AND page_number = ?",
                    (page.mean_confidence, low, document_id, page.page_number),
                )
            else:
                conn.execute(
                    "UPDATE document_page_ocr SET engine = ?, engine_tag = ?, "
                    "mean_confidence = ?, low_confidence = ?, recorded_at = ?, "
                    "reviewed_at = NULL, review_note = NULL "
                    "WHERE document_id = ? AND page_number = ?",
                    (
                        page.engine,
                        engine_tag,
                        page.mean_confidence,
                        low,
                        timestamp,
                        document_id,
                        page.page_number,
                    ),
                )
        for stale_page in existing:
            conn.execute(
                "DELETE FROM document_page_ocr WHERE document_id = ? AND page_number = ?",
                (document_id, stale_page),
            )
        awaiting = _refresh_document_flag(conn, document_id)

    if awaiting:
        log.info(
            "document %s has %d low-confidence page(s) awaiting review", document_id, awaiting
        )
    return FlagUpdate(pages_recorded=len(results), pages_awaiting_review=awaiting)


def list_flagged(conn: sqlite3.Connection) -> list[FlaggedPage]:
    """Return low-confidence pages that have not been reviewed."""
    rows = conn.execute(
        "SELECT d.id AS document_id, d.title, p.page_number, p.engine, p.mean_confidence "
        "FROM document_page_ocr p JOIN document d ON d.id = p.document_id "
        "WHERE p.low_confidence = 1 AND p.reviewed_at IS NULL "
        "ORDER BY d.title, d.id, p.page_number"
    ).fetchall()
    return [
        FlaggedPage(
            document_id=row["document_id"],
            title=row["title"] or "",
            page_number=row["page_number"],
            engine=row["engine"],
            mean_confidence=row["mean_confidence"],
        )
        for row in rows
    ]


def mark_reviewed(
    conn: sqlite3.Connection,
    document_id: int,
    page_number: int | None = None,
    note: str | None = None,
    now: str | None = None,
) -> int:
    """Mark flagged pages as reviewed. Returns the number of pages cleared.

    With page_number, clears that page; without it, clears every flagged page
    of the document. The recorded confidence is kept. The document flag
    clears once no flagged page remains unreviewed.

    Raises:
        ValueError: if the document, or the given page's OCR record, does not exist.
    """
    timestamp = now or _now()
    cleaned_note = (note or "").strip() or None
    with conn:
        _require_document(conn, document_id)
        query = (
            "UPDATE document_page_ocr SET reviewed_at = ?, review_note = ? "
            "WHERE document_id = ? AND low_confidence = 1 AND reviewed_at IS NULL"
        )
        parameters: list[object] = [timestamp, cleaned_note, document_id]
        if page_number is not None:
            known = conn.execute(
                "SELECT 1 FROM document_page_ocr WHERE document_id = ? AND page_number = ?",
                (document_id, page_number),
            ).fetchone()
            if known is None:
                raise ValueError(
                    f"No OCR record for page {page_number} of document {document_id}"
                )
            query += " AND page_number = ?"
            parameters.append(page_number)
        cleared = conn.execute(query, parameters).rowcount
        _refresh_document_flag(conn, document_id)

    if cleared:
        log.info("document %s: %d low-confidence page(s) marked reviewed", document_id, cleared)
    return cleared
