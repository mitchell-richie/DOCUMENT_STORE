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
    assert applied == ["0001_initial.sql"]

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for expected in ("source_file", "document", "chunk", "event", "entity_mention"):
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