"""SQLite connection factory with project-wide settings applied."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with foreign keys, WAL journaling, and sqlite-vec loaded."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    load_vec_extension(conn)
    return conn


def load_vec_extension(conn: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into an open connection."""
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)