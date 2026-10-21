"""Tests for external records on the `external` route (STORY-2.8, STORY-4.10)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from document_store.config import RoutingConfig
from document_store.constants import EXTERNAL_SYSTEMS
from document_store.ingest import routing
from document_store.ingest.documents import create_or_update_document
from document_store.ingest.external import ensure_external_record, external_system_for
from document_store.ingest.pipeline import ingest_folder
from document_store.ingest.register import register_file, sha256_of
from document_store.ingest.review import reclassify
from document_store.ingest.routing import build_router

BANK_STATEMENT = "bank_statement_synthetic_2024-01.pdf"


def _external_records(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        "SELECT document_id, external_system, external_id FROM external_record ORDER BY id"
    ).fetchall()
    return [(row["document_id"], row["external_system"], row["external_id"]) for row in rows]


def _chunk_count(conn: sqlite3.Connection, document_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM chunk WHERE document_id = ?", (document_id,)
    ).fetchone()[0]


@pytest.fixture
def originals_with_statement(originals: Path, fixtures_dir: Path) -> Path:
    (originals / "statements").mkdir()
    shutil.copy(fixtures_dir / BANK_STATEMENT, originals / "statements" / BANK_STATEMENT)
    return originals


def test_financial_statement_gets_document_and_external_record_and_no_chunks(
    conn: sqlite3.Connection, classifier, router, originals_with_statement: Path
) -> None:
    summary = ingest_folder(
        conn, classifier, router, originals_with_statement, originals_with_statement
    )

    assert summary.documents_created == 3
    assert summary.external_records_created == 1
    row = conn.execute(
        "SELECT id, doc_class, processing_route FROM document WHERE title = ?",
        (BANK_STATEMENT,),
    ).fetchone()
    assert (row["doc_class"], row["processing_route"]) == ("financial_statement", "external")

    expected_id = sha256_of(originals_with_statement / "statements" / BANK_STATEMENT)
    assert _external_records(conn) == [(row["id"], "bank_statement_tool", expected_id)]
    assert _chunk_count(conn, row["id"]) == 0


def test_documents_on_other_routes_get_no_external_record(
    conn: sqlite3.Connection, classifier, router, originals: Path
) -> None:
    ingest_folder(conn, classifier, router, originals, originals)
    assert _external_records(conn) == []


def test_reingestion_creates_no_second_external_record(
    conn: sqlite3.Connection, classifier, router, originals_with_statement: Path
) -> None:
    root = originals_with_statement
    ingest_folder(conn, classifier, router, root, root)
    summary = ingest_folder(conn, classifier, router, root, root)

    assert summary.external_records_created == 0
    assert len(_external_records(conn)) == 1


def test_duplicate_already_more_restrictive_gets_no_external_record(
    conn: sqlite3.Connection, classifier, router, originals_with_statement: Path
) -> None:
    # The same content also sits under in_camera, so the document is local_only
    # and its content is not handed to the external tool.
    root = originals_with_statement
    shutil.copy(root / "statements" / BANK_STATEMENT, root / "in_camera" / BANK_STATEMENT)
    ingest_folder(conn, classifier, router, root, root)

    route = conn.execute(
        "SELECT processing_route FROM document WHERE title = ?", (BANK_STATEMENT,)
    ).fetchone()["processing_route"]
    assert route == "local_only"
    assert _external_records(conn) == []


def test_reclassifying_to_financial_statement_creates_external_record(
    conn: sqlite3.Connection, router, fixtures_dir: Path
) -> None:
    path = fixtures_dir / "native.pdf"
    source = register_file(conn, path).source_file_id
    document_id = create_or_update_document(
        conn, source, "unclassified", "local_only", "native.pdf"
    ).document_id

    assert reclassify(conn, router, document_id, "financial_statement", "it is a statement")

    assert _external_records(conn) == [(document_id, "bank_statement_tool", sha256_of(path))]


def test_ensure_external_record_is_idempotent(
    conn: sqlite3.Connection, fixtures_dir: Path
) -> None:
    source = register_file(conn, fixtures_dir / BANK_STATEMENT).source_file_id
    document_id = create_or_update_document(
        conn, source, "financial_statement", "external", BANK_STATEMENT
    ).document_id

    assert ensure_external_record(conn, document_id) is True
    assert ensure_external_record(conn, document_id) is False
    assert len(_external_records(conn)) == 1


def test_ensure_external_record_rejects_unknown_document(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="No document"):
        ensure_external_record(conn, 999)


def test_external_system_for_unknown_class_raises() -> None:
    assert external_system_for("financial_statement") == EXTERNAL_SYSTEMS["financial_statement"]
    with pytest.raises(ValueError, match="No external system"):
        external_system_for("correspondence")


def test_router_rejects_external_route_for_class_without_external_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = {
        "in_camera": "local_only",
        "financial_statement": "external",
        "receipt": "external",  # no external system defined for receipts
        "court_filing": "standard",
        "correspondence": "standard",
        "other": "standard",
        "unclassified": "local_only",
    }
    with pytest.raises(ValueError, match="no external system.*receipt"):
        build_router(RoutingConfig(mapping=mapping))

    monkeypatch.setitem(routing.EXTERNAL_SYSTEMS, "receipt", "receipt_tool")
    assert build_router(RoutingConfig(mapping=mapping)).route_for("receipt") == "external"
