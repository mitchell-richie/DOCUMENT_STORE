"""Tests for the sqlite-vec helpers."""

import sqlite3

import pytest

from document_store.db.vector import (
    delete_embeddings,
    ensure_vector_table,
    insert_embeddings,
    list_vector_tables,
    nearest,
    vector_table_name,
)


def test_table_name_includes_model_and_dimension() -> None:
    assert vector_table_name("bge-m3", 1024) == "chunk_embedding_bge_m3_1024"


@pytest.mark.parametrize("dims", [0, -1])
def test_non_positive_dimensions_rejected(dims: int) -> None:
    with pytest.raises(ValueError):
        vector_table_name("bge-m3", dims)


def test_nearest_neighbour_returns_closest_first(conn: sqlite3.Connection) -> None:
    table = ensure_vector_table(conn, "test-model", 4)
    insert_embeddings(
        conn,
        table,
        [
            (1, [1.0, 0.0, 0.0, 0.0]),
            (2, [0.0, 1.0, 0.0, 0.0]),
            (3, [0.9, 0.1, 0.0, 0.0]),
        ],
    )
    results = nearest(conn, table, [1.0, 0.0, 0.0, 0.0], limit=2)
    assert [chunk_id for chunk_id, _ in results] == [1, 3]


def test_wrong_dimension_rejected(conn: sqlite3.Connection) -> None:
    table = ensure_vector_table(conn, "test-model", 4)
    with pytest.raises(sqlite3.Error):
        insert_embeddings(conn, table, [(1, [1.0, 0.0])])


def test_changing_dimension_creates_new_table(conn: sqlite3.Connection) -> None:
    ensure_vector_table(conn, "test-model", 4)
    ensure_vector_table(conn, "test-model", 8)
    assert set(list_vector_tables(conn)) == {
        "chunk_embedding_test_model_4",
        "chunk_embedding_test_model_8",
    }


def test_delete_removes_vector(conn: sqlite3.Connection) -> None:
    table = ensure_vector_table(conn, "test-model", 4)
    insert_embeddings(conn, table, [(1, [1.0, 0.0, 0.0, 0.0]), (2, [0.0, 1.0, 0.0, 0.0])])
    delete_embeddings(conn, table, [1])
    results = nearest(conn, table, [1.0, 0.0, 0.0, 0.0], limit=5)
    assert [chunk_id for chunk_id, _ in results] == [2]