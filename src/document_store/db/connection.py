"""SQLite connection factory with project-wide settings applied."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced and WAL journaling."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn