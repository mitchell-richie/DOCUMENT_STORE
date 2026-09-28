"""Tests for the FTS5 keyword index."""

import sqlite3

from conftest import insert_chunk


def _search(conn: sqlite3.Connection, query: str) -> list[int]:
    rows = conn.execute(
        "SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY rank",
        (query,),
    ).fetchall()
    return [row["rowid"] for row in rows]


def test_inserted_chunk_is_searchable(conn: sqlite3.Connection) -> None:
    chunk_id = insert_chunk(conn, "The contract was signed in March.")
    assert _search(conn, "contract") == [chunk_id]


def test_phrase_with_punctuation_is_searchable(conn: sqlite3.Connection) -> None:
    chunk_id = insert_chunk(conn, "Letter from O'Brien dated 3 May.")
    assert _search(conn, '"O\'Brien"') == [chunk_id]


def test_diacritics_are_folded(conn: sqlite3.Connection) -> None:
    chunk_id = insert_chunk(conn, "Reunión with Señor García.")
    assert _search(conn, "garcia") == [chunk_id]


def test_update_replaces_index_terms(conn: sqlite3.Connection) -> None:
    chunk_id = insert_chunk(conn, "original wording")
    conn.execute("UPDATE chunk SET text = 'revised wording' WHERE id = ?", (chunk_id,))
    assert _search(conn, "revised") == [chunk_id]
    assert _search(conn, "original") == []


def test_delete_removes_index_terms(conn: sqlite3.Connection) -> None:
    chunk_id = insert_chunk(conn, "to be deleted")
    conn.execute("DELETE FROM chunk WHERE id = ?", (chunk_id,))
    assert _search(conn, "deleted") == []