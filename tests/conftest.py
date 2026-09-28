"""Shared fixtures."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from document_store.db.connection import connect
from document_store.db.migrate import migrate


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated database with sqlite-vec loaded."""
    connection = connect(tmp_path / "test.sqlite")
    migrate(connection)
    yield connection
    connection.close()


def insert_chunk(conn: sqlite3.Connection, text: str, ordinal: int = 0) -> int:
    """Insert a chunk under a shared test document and return its ID."""
    conn.execute(
        "INSERT OR IGNORE INTO source_file (id, sha256, size_bytes, imported_at) "
        "VALUES (1, 'test-hash', 1, '2025-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO document (id, source_file_id, doc_class, processing_route, created_at) "
        "VALUES (1, 1, 'other', 'standard', '2025-01-01T00:00:00+00:00')"
    )
    cursor = conn.execute(
        "INSERT INTO chunk (document_id, ordinal, text, char_start, char_end, chunk_method) "
        "VALUES (1, ?, ?, 0, ?, 'test')",
        (ordinal, text, len(text)),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid