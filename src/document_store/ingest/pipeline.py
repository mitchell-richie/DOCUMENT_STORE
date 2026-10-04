"""Ingestion pipeline: register, classify, route, and record each file."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from document_store.constants import PROCESSING_ROUTES  # noqa: F401 (route vocabulary)
from document_store.ingest.classify import Classifier, relative_to_originals
from document_store.ingest.documents import create_or_update_document
from document_store.ingest.register import mime_type_for, register_file
from document_store.ingest.routing import Router, route_document

log = logging.getLogger(__name__)

EXPECTED_ERRORS = (OSError, ValueError, sqlite3.Error)


@dataclass
class IngestSummary:
    documents_created: int = 0
    documents_existing: int = 0
    routes_upgraded: int = 0
    skipped: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Counts and failed file names, for the run log. No document content."""
        return {
            "documents_created": self.documents_created,
            "documents_existing": self.documents_existing,
            "routes_upgraded": self.routes_upgraded,
            "files_skipped": len(self.skipped),
            "files_failed": [path.name for path, _ in self.errors],
        }    


def check_within_originals(originals_root: Path, target: Path) -> None:
    """Raise ValueError unless target is inside originals_root."""
    relative_to_originals(originals_root, target)


def ingest_file(
    conn: sqlite3.Connection,
    classifier: Classifier,
    router: Router,
    originals_root: Path,
    path: Path,
) -> tuple[bool, bool]:
    """Ingest one file. Returns (document_created, route_changed)."""
    registration = register_file(conn, path)
    doc_class, route = route_document(classifier, router, originals_root, path)
    result = create_or_update_document(
        conn,
        source_file_id=registration.source_file_id,
        doc_class=doc_class,
        route=route,
        title=path.name,
    )
    return result.created, result.route_changed


def ingest_folder(
    conn: sqlite3.Connection,
    classifier: Classifier,
    router: Router,
    originals_root: Path,
    root: Path,
) -> IngestSummary:
    """Ingest every supported file beneath root. Per-file failures are recorded."""
    summary = IngestSummary()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if mime_type_for(path) is None:
            log.info("skipping unsupported file: %s", path.name)
            summary.skipped.append(path)
            continue
        try:
            created, route_changed = ingest_file(
                conn, classifier, router, originals_root, path
            )
        except EXPECTED_ERRORS as exc:
            log.error("failed to ingest %s: %s", path.name, exc)
            summary.errors.append((path, str(exc)))
            continue

        if created:
            summary.documents_created += 1
        elif route_changed:
            summary.routes_upgraded += 1
        else:
            summary.documents_existing += 1
    return summary

