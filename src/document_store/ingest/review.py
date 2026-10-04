"""Classification review: list unclassified documents and reclassify them."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from document_store.constants import DOC_CLASSES
from document_store.ingest.documents import _apply_route_change
from document_store.ingest.routing import Router

UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class UnclassifiedDocument:
    document_id: int
    title: str
    processing_route: str


def list_unclassified(conn: sqlite3.Connection) -> list[UnclassifiedDocument]:
    """Return top-level documents whose class is still the default."""
    rows = conn.execute(
        "SELECT id, title, processing_route FROM document "
        "WHERE doc_class = ? AND parent_id IS NULL ORDER BY title, id",
        (UNCLASSIFIED,),
    ).fetchall()
    return [
        UnclassifiedDocument(
            document_id=row["id"],
            title=row["title"] or "",
            processing_route=row["processing_route"],
        )
        for row in rows
    ]


def reclassify(
    conn: sqlite3.Connection,
    router: Router,
    document_id: int,
    new_class: str,
    reason: str,
    risk_acknowledged: bool = False,
    now: str | None = None,
) -> bool:
    """Set a document's class and route. Returns True if anything changed.

    The title is not changed: a manual decision has no source location to
    take a title from.

    Raises:
        ValueError: for an unrecognised class, an empty reason, or a missing document.
        RiskAcknowledgementRequired: if the new route is less restrictive and
            the risk has not been acknowledged.
    """
    if new_class not in DOC_CLASSES:
        raise ValueError(f"Unrecognised doc_class {new_class!r}")
    if new_class == UNCLASSIFIED:
        raise ValueError("cannot manually set a document to unclassified")
    if not reason.strip():
        raise ValueError("a reason is required for reclassification")

    new_route = router.route_for(new_class)
    timestamp = now or datetime.now(UTC).isoformat()

    with conn:
        row = conn.execute(
            "SELECT doc_class, processing_route FROM document WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No document with id {document_id}")

        old_class = row["doc_class"]
        current_route = row["processing_route"]
        if old_class == new_class and current_route == new_route:
            return False

        placeholder = old_class == UNCLASSIFIED

        if new_route != current_route:
            origin = "from unclassified " if placeholder else ""
            _apply_route_change(
                conn,
                document_id,
                current_route,
                new_route,
                f"reclassified {origin}to {new_class}: {reason}",
                risk_acknowledged,
                timestamp,
                placeholder_transition=placeholder,
            )

        if old_class != new_class:
            conn.execute(
                "UPDATE document SET doc_class = ? WHERE id = ?", (new_class, document_id)
            )
            conn.execute(
                "INSERT INTO document_class_change "
                "(document_id, from_class, to_class, reason, changed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (document_id, old_class, new_class, reason, timestamp),
            )
        return True