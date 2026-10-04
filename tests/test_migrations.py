"""Tests for schema migrations."""

import sqlite3
from pathlib import Path

import pytest

from document_store.db.connection import connect
from document_store.db.migrate import migrate


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "test.sqlite")
    yield connection
    connection.close()


def test_migrations_apply_to_empty_database(conn: sqlite3.Connection) -> None:
    applied = migrate(conn)
    assert applied == [
        "0001_initial.sql", "0002_fts.sql", "0003_document_ingest.sql",
        "0004_document_class_change.sql", "0005_unclassified_class.sql"
        ]

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for expected in (
        "event", "entity_mention", "email_thread", "chunk_fts_docsize",
        "chunk_fts_config", "chunk_fts", "review_item", "processing_run",
        "chunk", "external_record", "schema_migrations", "source_file_location",
        "event_entity", "document", "chunk_fts_data", "chunk_fts_idx",
        "relationship", "email_message", "entity", "source_file",
        "entity_alias", "event_evidence", "message_participant",
        "document_route_change",
        ):
        assert expected in tables


def test_migrations_are_idempotent(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert migrate(conn) == []


def test_invalid_doc_class_rejected(conn: sqlite3.Connection) -> None:
    migrate(conn)
    conn.execute(
        "INSERT INTO source_file (id, sha256, size_bytes, imported_at) "
        "VALUES (1, 'abc', 10, '2025-01-01T00:00:00+00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO document (source_file_id, doc_class, processing_route, created_at) "
            "VALUES (1, 'not_a_class', 'standard', '2025-01-01T00:00:00+00:00')"
        )


def test_foreign_keys_enforced(conn: sqlite3.Connection) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO document (source_file_id, doc_class, processing_route, created_at) "
            "VALUES (999, 'other', 'standard', '2025-01-01T00:00:00+00:00')"
        )


def test_duplicate_sha256_rejected(conn: sqlite3.Connection) -> None:
    migrate(conn)
    insert = (
        "INSERT INTO source_file (sha256, size_bytes, imported_at) "
        "VALUES ('same', 10, '2025-01-01T00:00:00+00:00')"
    )
    conn.execute(insert)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert)