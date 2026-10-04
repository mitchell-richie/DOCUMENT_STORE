"""Tests for classification review (STORY-2.5)."""

import sqlite3
from pathlib import Path

import pytest

from document_store.config import RoutingConfig
from document_store.ingest.documents import RiskAcknowledgementRequired, create_or_update_document
from document_store.ingest.register import register_file
from document_store.ingest.review import list_unclassified, reclassify
from document_store.ingest.routing import build_router

MAPPING = {
    "in_camera": "local_only",
    "financial_statement": "external",
    "receipt": "standard",
    "court_filing": "standard",
    "correspondence": "standard",
    "other": "standard",
    "unclassified": "local_only",
}


@pytest.fixture
def router():
    return build_router(RoutingConfig(mapping=MAPPING))


@pytest.fixture
def other_doc(conn: sqlite3.Connection, fixtures_dir: Path) -> int:
    source = register_file(conn, fixtures_dir / "native.pdf").source_file_id
    return create_or_update_document(conn, source, "other", "standard", "native.pdf").document_id

@pytest.fixture
def in_camera_doc(conn: sqlite3.Connection, fixtures_dir: Path) -> int:
    source = register_file(conn, fixtures_dir / "scanned.pdf").source_file_id
    return create_or_update_document(conn, source, "in_camera", "local_only", "scanned.pdf").document_id

@pytest.fixture
def unclassified_doc(conn: sqlite3.Connection, fixtures_dir: Path) -> int:
    source = register_file(conn, fixtures_dir / "native.pdf").source_file_id
    return create_or_update_document(
        conn, source, "unclassified", "local_only", "native.pdf"
    ).document_id


@pytest.fixture
def reviewed_other_doc(conn: sqlite3.Connection, fixtures_dir: Path) -> int:
    source = register_file(conn, fixtures_dir / "sample.docx").source_file_id
    return create_or_update_document(
        conn, source, "other", "standard", "sample.docx"
    ).document_id

def _row(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT doc_class, processing_route, title FROM document WHERE id = ?", (document_id,)
    ).fetchone()


def test_list_excludes_reviewed_other(conn, reviewed_other_doc: int) -> None:
    assert list_unclassified(conn) == []


def test_reclassify_from_unclassified_needs_no_acknowledgment(
    conn, router, unclassified_doc: int
) -> None:
    assert reclassify(conn, router, unclassified_doc, "correspondence", reason="letter") is True
    row = _row(conn, unclassified_doc)
    assert row["doc_class"] == "correspondence"
    assert row["processing_route"] == "standard"


def test_cannot_reclassify_to_unclassified(conn, router, reviewed_other_doc: int) -> None:
    with pytest.raises(ValueError, match="unclassified"):
        reclassify(conn, router, reviewed_other_doc, "unclassified", reason="reset")


def test_list_shows_unclassified_documents(conn, unclassified_doc: int) -> None:
    docs = list_unclassified(conn)
    assert [(d.document_id, d.title) for d in docs] == [(unclassified_doc, "native.pdf")]


def test_list_excludes_classified_documents(conn, fixtures_dir: Path) -> None:
    source = register_file(conn, fixtures_dir / "sample.docx").source_file_id
    create_or_update_document(conn, source, "correspondence", "standard", "sample.docx")
    assert list_unclassified(conn) == []


def test_reclassify_updates_class_and_route_and_logs(conn, router, unclassified_doc: int) -> None:
    changed = reclassify(
        conn,
        router,
        unclassified_doc,
        "correspondence",
        reason="letter from solicitor",
        risk_acknowledged=True
        )
    assert changed is True

    row = _row(conn, unclassified_doc)
    assert row["doc_class"] == "correspondence"
    assert row["processing_route"] == "standard"
    assert row["title"] == "native.pdf"  # title unchanged

    class_log = conn.execute(
        "SELECT from_class, to_class, reason FROM document_class_change WHERE document_id = ?",
        (unclassified_doc,),
    ).fetchall()
    assert [tuple(r) for r in class_log] == [("unclassified", "correspondence", "letter from solicitor")]


def test_reclassify_to_less_restrictive_route_needs_acknowledgment(
    conn, router, in_camera_doc: int
) -> None:
    with pytest.raises(RiskAcknowledgementRequired):
        reclassify(conn, router, in_camera_doc, "correspondence", reason="now public")

    row = _row(conn, in_camera_doc)
    assert row["doc_class"] == "in_camera"
    assert row["processing_route"] == "local_only"


def test_reclassify_with_acknowledgment_is_audited(conn, router, unclassified_doc: int) -> None:
    reclassify(conn, router, unclassified_doc, "correspondence", "now public", risk_acknowledged=True)

    audit = conn.execute(
        "SELECT from_route, to_route, is_downgrade, risk_acknowledged "
        "FROM document_route_change WHERE document_id = ?",
        (unclassified_doc,),
    ).fetchall()
    assert [tuple(r) for r in audit] == [("local_only", "standard", 1, 1)]


def test_same_class_and_route_is_no_op(conn, router, in_camera_doc: int) -> None:
    assert reclassify(conn, router, in_camera_doc, "in_camera", reason="no change") is False


def test_empty_reason_rejected(conn, router, unclassified_doc: int) -> None:
    with pytest.raises(ValueError, match="reason"):
        reclassify(conn, router, unclassified_doc, "correspondence", reason="   ")


def test_unknown_class_rejected(conn, router, unclassified_doc: int) -> None:
    with pytest.raises(ValueError, match="Unrecognised"):
        reclassify(conn, router, unclassified_doc, "not_a_class", reason="x")


def test_reclassified_document_is_not_reverted_by_reingestion(
    conn, router, unclassified_doc: int, fixtures_dir: Path
) -> None:
    reclassify(
        conn,
        router,
        unclassified_doc,
        "correspondence",
        reason="letter",
        risk_acknowledged=True
        )
    source = conn.execute(
        "SELECT source_file_id FROM document WHERE id = ?", (unclassified_doc,)
    ).fetchone()["source_file_id"]

    # Re-ingestion at an unmatched path classifies as "other" (route local_only).
    create_or_update_document(conn, source, "other", "local_only", "elsewhere.pdf")

    row = _row(conn, unclassified_doc)
    assert row["doc_class"] == "correspondence"  # sticky
    assert row["title"] == "native.pdf"