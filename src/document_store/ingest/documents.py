"""Document records: one top-level document per source file.

Automatic changes (ingestion) can only make a route more restrictive.
Downgrades are manual and require acknowledgment of the risk.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from document_store.constants import PROCESSING_ROUTES, ROUTE_RESTRICTIVENESS

log = logging.getLogger(__name__)


DOWNGRADE_WARNING = (
    "Downgrading this document's processing route may allow its content to be "
    "processed in a less restricted way, including cloud services where the new "
    "route permits them. Confirm the document may be handled this way before "
    "proceeding."
)


class RiskAcknowledgementRequired(Exception):
    """Raised when a downgrade is requested without acknowledging the risk."""


@dataclass(frozen=True)
class DocumentResult:
    document_id: int
    created: bool
    route_changed: bool


def most_restrictive(routes: list[str]) -> str:
    """Return the most restrictive route in a list."""
    if not routes:
        raise ValueError("at least one route is required")
    for route in routes:
        if route not in PROCESSING_ROUTES:
            raise ValueError(f"Unrecognised processing_route {route!r}")
    return max(routes, key=ROUTE_RESTRICTIVENESS.__getitem__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_or_update_document(
    conn: sqlite3.Connection,
    source_file_id: int,
    doc_class: str,
    route: str,
    title: str,
    now: str | None = None,
) -> DocumentResult:
    """Create the top-level document for a source file, or upgrade its route.

    If a document already exists, the route becomes the more restrictive of
    the existing route and the incoming route. A less restrictive incoming
    route is ignored: automatic changes never downgrade.

    When an upgrade occurs, doc_class and title are replaced with the values
    from the registration that caused the upgrade, so the title always
    reflects whichever location made the document most restrictive,
    regardless of ingestion order.
    """
    timestamp = now or _now()
    with conn:
        row = conn.execute(
            "SELECT id, doc_class, processing_route FROM document "
            "WHERE source_file_id = ? AND parent_id IS NULL",
            (source_file_id,),
        ).fetchone()

        if row is None:
            cursor = conn.execute(
                "INSERT INTO document (source_file_id, title, doc_class, processing_route, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (source_file_id, title, doc_class, route, timestamp),
            )
            assert cursor.lastrowid is not None
            return DocumentResult(document_id=cursor.lastrowid, created=True, route_changed=False)

        document_id = row["id"]
        current = row["processing_route"]
        effective = most_restrictive([current, route])

        if ROUTE_RESTRICTIVENESS[effective] <= ROUTE_RESTRICTIVENESS[current]:
            return DocumentResult(document_id=document_id, created=False, route_changed=False)

        conn.execute(
            "UPDATE document SET processing_route = ?, doc_class = ?, title = ? WHERE id = ?",
            (effective, doc_class, title, document_id),
        )
        conn.execute(
            "INSERT INTO document_route_change "
            "(document_id, from_route, to_route, change_kind, is_downgrade, "
            " risk_acknowledged, reason, changed_at) "
            "VALUES (?, ?, ?, 'automatic', 0, 0, 'duplicate or re-ingestion at a more "
            "restrictive location', ?)",
            (document_id, current, effective, timestamp),
        )
        log.info("document %s upgraded from %s to %s", document_id, current, effective)
        return DocumentResult(document_id=document_id, created=False, route_changed=True)


def change_route(
    conn: sqlite3.Connection,
    document_id: int,
    new_route: str,
    reason: str,
    risk_acknowledged: bool = False,
    now: str | None = None,
) -> bool:
    """Manually change a document's route. Returns True if the route changed.

    Upgrades need no acknowledgment. Downgrades require risk_acknowledged=True.

    Raises:
        RiskAcknowledgementRequired: for a downgrade without acknowledgment.
        ValueError: for an unrecognised route or a missing document.
    """
    if new_route not in PROCESSING_ROUTES:
        raise ValueError(f"Unrecognised processing_route {new_route!r}")

    timestamp = now or _now()
    with conn:
        row = conn.execute(
            "SELECT processing_route FROM document WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No document with id {document_id}")

        current = row["processing_route"]
        if new_route == current:
            return False

        is_downgrade = ROUTE_RESTRICTIVENESS[new_route] < ROUTE_RESTRICTIVENESS[current]
        if is_downgrade and not risk_acknowledged:
            raise RiskAcknowledgementRequired(DOWNGRADE_WARNING)

        conn.execute(
            "UPDATE document SET processing_route = ? WHERE id = ?",
            (new_route, document_id),
        )
        conn.execute(
            "INSERT INTO document_route_change "
            "(document_id, from_route, to_route, change_kind, is_downgrade, "
            " risk_acknowledged, reason, changed_at) "
            "VALUES (?, ?, ?, 'manual', ?, ?, ?, ?)",
            (
                document_id,
                current,
                new_route,
                int(is_downgrade),
                int(is_downgrade and risk_acknowledged),
                reason,
                timestamp,
            ),
        )
        return True