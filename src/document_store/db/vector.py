"""Vector index helpers (sqlite-vec).

Each embedding model and dimension pair gets its own vec0 table, named from
the model identifier and dimension. Vectors from different models are never
mixed, and a configuration change creates a new table.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence

import sqlite_vec

_UNSAFE = re.compile(r"[^a-z0-9]+")
_PREFIX = "chunk_embedding_"


def vector_table_name(model_id: str, dimensions: int) -> str:
    """Return the table name for a model and dimension pair.

    Example: ("bge-m3", 1024) -> "chunk_embedding_bge_m3_1024"
    """
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    slug = _UNSAFE.sub("_", model_id.lower()).strip("_")
    if not slug:
        raise ValueError(f"model_id produces an empty table name: {model_id!r}")
    return f"{_PREFIX}{slug}_{dimensions}"


def ensure_vector_table(conn: sqlite3.Connection, model_id: str, dimensions: int) -> str:
    """Create the vector table for a model and dimension if absent. Returns its name."""
    name = vector_table_name(model_id, dimensions)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {name} USING vec0("
        f"chunk_id INTEGER PRIMARY KEY, embedding float[{dimensions}])"
    )
    return name


def list_vector_tables(conn: sqlite3.Connection) -> list[str]:
    """Return the names of all embedding tables."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name LIKE 'chunk\\_embedding\\_%' ESCAPE '\\' "
        "AND sql LIKE 'CREATE VIRTUAL TABLE%'"
    ).fetchall()
    return [row["name"] for row in rows]


def insert_embeddings(
    conn: sqlite3.Connection,
    table: str,
    items: Sequence[tuple[int, Sequence[float]]],
) -> None:
    """Insert (chunk_id, vector) pairs. Vector length must match the table dimension."""
    conn.executemany(
        f"INSERT INTO {table} (chunk_id, embedding) VALUES (?, ?)",
        [(chunk_id, sqlite_vec.serialize_float32(list(vec))) for chunk_id, vec in items],
    )


def nearest(
    conn: sqlite3.Connection,
    table: str,
    query: Sequence[float],
    limit: int,
) -> list[tuple[int, float]]:
    """Return (chunk_id, distance) pairs for the nearest vectors, closest first."""
    rows = conn.execute(
        f"SELECT chunk_id, distance FROM {table} "
        "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
        (sqlite_vec.serialize_float32(list(query)), limit),
    ).fetchall()
    return [(row["chunk_id"], row["distance"]) for row in rows]


def delete_embeddings(conn: sqlite3.Connection, table: str, chunk_ids: Sequence[int]) -> None:
    """Remove vectors for the given chunk IDs."""
    conn.executemany(
        f"DELETE FROM {table} WHERE chunk_id = ?",
        [(chunk_id,) for chunk_id in chunk_ids],
    )