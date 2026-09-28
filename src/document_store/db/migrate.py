"""Apply versioned SQL migrations in order.

Each migration file is named NNNN_description.sql. Applied versions are
recorded in schema_migrations. Each migration runs in its own transaction.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from importlib import resources

MIGRATIONS_PACKAGE = "document_store.db.migrations"


def _migration_files() -> list[tuple[int, str, str]]:
    files = sorted(
        (f for f in resources.files(MIGRATIONS_PACKAGE).iterdir() if f.name.endswith(".sql")),
        key=lambda f: f.name,
    )
    return [
        (int(f.name.split("_", 1)[0]), f.name, f.read_text(encoding="utf-8"))
        for f in files
    ]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply all pending migrations. Returns the names of newly applied files."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

    newly_applied: list[str] = []
    for version, name, sql in _migration_files():
        if version in applied:
            continue
        now = datetime.now(UTC).isoformat()
        script = (
            "BEGIN;\n"
            f"{sql}\n"
            f"INSERT INTO schema_migrations (version, name, applied_at) "
            f"VALUES ({version}, '{name}', '{now}');\n"
            "COMMIT;\n"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        newly_applied.append(name)
    return newly_applied