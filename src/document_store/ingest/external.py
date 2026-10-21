"""External records: pointers for documents handled by another tool.

A document on the `external` route (for example, a bank statement) is
registered for traceability but its content is never chunked, embedded, or
extracted here. An external_record links it to the system that does handle
it. The link is keyed on the source file's SHA-256, which the other tool can
compute from the same file; summary_date_range is left for that tool to fill.
"""

from __future__ import annotations

import logging
import sqlite3

from document_store.constants import EXTERNAL_SYSTEMS

log = logging.getLogger(__name__)

EXTERNAL_ROUTE = "external"


def external_system_for(doc_class: str) -> str:
    """Return the external system that handles a doc_class.

    Raises:
        ValueError: if no external system is defined for the class.
    """
    try:
        return EXTERNAL_SYSTEMS[doc_class]
    except KeyError:
        raise ValueError(f"No external system is defined for doc_class {doc_class!r}") from None


def ensure_external_record(conn: sqlite3.Connection, document_id: int) -> bool:
    """Create the external_record for a document if its route is `external`.

    Returns True if a record was created. A document whose route is not
    `external`, or that already has its record, is left unchanged. The record
    is keyed on (external_system, source sha256), so re-ingestion and
    reclassification never create a second one.

    Raises:
        ValueError: if the document does not exist, or its class has no
            external system.
    """
    with conn:
        row = conn.execute(
            "SELECT d.doc_class, d.processing_route, s.sha256 "
            "FROM document d JOIN source_file s ON s.id = d.source_file_id "
            "WHERE d.id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No document with id {document_id}")
        if row["processing_route"] != EXTERNAL_ROUTE:
            return False

        system = external_system_for(row["doc_class"])
        cursor = conn.execute(
            "INSERT OR IGNORE INTO external_record (document_id, external_system, external_id) "
            "VALUES (?, ?, ?)",
            (document_id, system, row["sha256"]),
        )
        created = cursor.rowcount == 1

    if created:
        log.info("document %s linked to external system %s", document_id, system)
    return created
