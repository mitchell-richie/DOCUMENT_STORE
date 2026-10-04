"""Tests for document record creation and route changes (STORY-2.8)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from document_store.ingest.documents import (
    RiskAcknowledgementRequired,
    change_route,
    create_or_update_document,
    most_restrictive,
)
from document_store.ingest.pipeline import ingest_folder
from document_store.ingest.register import register_file


@pytest.fixture
def source_file_id(conn: sqlite3.Connection, fixtures_dir: Path) -> int:
    return register_file(conn, fixtures_dir / "native.pdf").source_file_id


def _route(conn: sqlite3.Connection, document_id: int) -> str:
    row = conn.execute(
        "SELECT processing_route FROM document WHERE id = ?", (document_id,)
    ).fetchone()
    return row["processing_route"]


def _audit_rows(conn: sqlite3.Connection, document_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM document_route_change WHERE document_id = ? ORDER BY id",
        (document_id,),
    ).fetchall()


def test_creates_document_with_title_class_and_route(
    conn: sqlite3.Connection, source_file_id: int
) -> None:
    result = create_or_update_document(
        conn, source_file_id, doc_class="correspondence", route="standard", title="native.pdf"
    )

    assert result.created is True
    row = conn.execute("SELECT * FROM document WHERE id = ?", (result.document_id,)).fetchone()
    assert row["title"] == "native.pdf"
    assert row["doc_class"] == "correspondence"
    assert row["processing_route"] == "standard"


def test_repeat_ingestion_creates_no_duplicate(
    conn: sqlite3.Connection, source_file_id: int
) -> None:
    first = create_or_update_document(conn, source_file_id, "correspondence", "standard", "n.pdf")
    second = create_or_update_document(conn, source_file_id, "correspondence", "standard", "n.pdf")

    assert second.document_id == first.document_id
    assert second.created is False
    assert second.route_changed is False
    assert conn.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 1


def test_duplicate_in_camera_location_upgrades_route(
    conn: sqlite3.Connection, source_file_id: int
) -> None:
    first = create_or_update_document(conn, source_file_id, "correspondence", "standard", "a.pdf")
    second = create_or_update_document(conn, source_file_id, "in_camera", "local_only", "b.pdf")

    assert second.route_changed is True
    row = conn.execute(
        "SELECT processing_route, doc_class, title FROM document WHERE id = ?",
        (first.document_id,),
    ).fetchone()
    assert row["processing_route"] == "local_only"
    assert row["doc_class"] == "in_camera"
    assert row["title"] == "b.pdf"


def test_title_follows_most_restrictive_regardless_of_order(
    conn: sqlite3.Connection, source_file_id: int
) -> None:
    # Most restrictive location seen first: later, less restrictive location
    # must not change the title.
    first = create_or_update_document(conn, source_file_id, "in_camera", "local_only", "b.pdf")
    create_or_update_document(conn, source_file_id, "correspondence", "standard", "a.pdf")

    row = conn.execute(
        "SELECT processing_route, title FROM document WHERE id = ?", (first.document_id,)
    ).fetchone()
    assert row["processing_route"] == "local_only"
    assert row["title"] == "b.pdf"


def test_title_is_order_independent(
    conn, classifier, router, originals: Path, fixtures_dir: Path
) -> None:
    """Whichever copy is more restrictive wins the title, regardless of
    which is ingested first."""
    # Swap which folder is processed first by renaming so in_camera sorts last.
    shutil.copy(fixtures_dir / "native.pdf", originals / "correspondence" / "z-copy.pdf")

    ingest_folder(conn, classifier, router, originals, originals)

    row = conn.execute("SELECT title, processing_route FROM document").fetchall()
    titles = {r["title"]: r["processing_route"] for r in row}
    assert titles.get("order.pdf") == "local_only"
    assert "z-copy.pdf" not in titles  # same content; no separate document


def test_automatic_path_never_downgrades(
    conn: sqlite3.Connection, source_file_id: int
) -> None:
    first = create_or_update_document(conn, source_file_id, "in_camera", "local_only", "b.pdf")
    create_or_update_document(conn, source_file_id, "correspondence", "standard", "a.pdf")

    row = conn.execute(
        "SELECT processing_route, doc_class, title FROM document WHERE id = ?",
        (first.document_id,),
    ).fetchone()
    assert row["processing_route"] == "local_only"
    assert row["doc_class"] == "in_camera"
    assert row["title"] == "b.pdf"
    assert _audit_rows(conn, first.document_id) == []


def test_manual_downgrade_without_acknowledgment_raises(
    conn: sqlite3.Connection, source_file_id: int
) -> None:
    doc = create_or_update_document(conn, source_file_id, "in_camera", "local_only", "n.pdf")

    with pytest.raises(RiskAcknowledgementRequired):
        change_route(conn, doc.document_id, "standard", reason="now public")

    assert _route(conn, doc.document_id) == "local_only"


def test_manual_downgrade_with_acknowledgment_is_audited(
    conn: sqlite3.Connection, source_file_id: int
) -> None:
    doc = create_or_update_document(conn, source_file_id, "in_camera", "local_only", "n.pdf")

    changed = change_route(
        conn, doc.document_id, "standard", reason="filed publicly", risk_acknowledged=True
    )

    assert changed is True
    assert _route(conn, doc.document_id) == "standard"
    audit = _audit_rows(conn, doc.document_id)
    assert audit[-1]["change_kind"] == "manual"
    assert audit[-1]["is_downgrade"] == 1
    assert audit[-1]["risk_acknowledged"] == 1
    assert audit[-1]["reason"] == "filed publicly"


def test_manual_upgrade_needs_no_acknowledgment(
    conn: sqlite3.Connection, source_file_id: int
) -> None:
    doc = create_or_update_document(conn, source_file_id, "correspondence", "standard", "n.pdf")

    assert change_route(conn, doc.document_id, "local_only", reason="sensitive") is True
    audit = _audit_rows(conn, doc.document_id)
    assert audit[-1]["is_downgrade"] == 0
    assert audit[-1]["risk_acknowledged"] == 0


def test_same_route_change_is_a_no_op(conn: sqlite3.Connection, source_file_id: int) -> None:
    doc = create_or_update_document(conn, source_file_id, "correspondence", "standard", "n.pdf")
    assert change_route(conn, doc.document_id, "standard", reason="none") is False
    assert _audit_rows(conn, doc.document_id) == []


def test_second_top_level_document_for_same_file_is_rejected(
    conn: sqlite3.Connection, source_file_id: int
) -> None:
    conn.execute(
        "INSERT INTO document (source_file_id, doc_class, processing_route, created_at) "
        "VALUES (?, 'other', 'local_only', 'x')",
        (source_file_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO document (source_file_id, doc_class, processing_route, created_at) "
            "VALUES (?, 'other', 'local_only', 'x')",
            (source_file_id,),
        )


@pytest.mark.parametrize(
    ("routes", "expected"),
    [
        (["standard", "local_only"], "local_only"),
        (["external", "index_only"], "index_only"),
        (["standard", "external"], "external"),
        (["standard"], "standard"),
    ],
)
def test_most_restrictive(routes: list[str], expected: str) -> None:
    assert most_restrictive(routes) == expected


def test_most_restrictive_rejects_empty_list() -> None:
    with pytest.raises(ValueError):
        most_restrictive([])