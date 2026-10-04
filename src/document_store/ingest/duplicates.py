"""Duplicate detection: files whose content is recorded at more than one path."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class DuplicateGroup:
    sha256: str
    source_file_id: int
    paths: list[str] = field(default_factory=list)


def find_duplicates(conn: sqlite3.Connection) -> list[DuplicateGroup]:
    """Return every source file recorded at more than one path, ordered by ID."""
    rows = conn.execute(
        """
        SELECT sf.id, sf.sha256, l.path
        FROM source_file AS sf
        JOIN source_file_location AS l ON l.source_file_id = sf.id
        WHERE sf.id IN (
            SELECT source_file_id
            FROM source_file_location
            GROUP BY source_file_id
            HAVING COUNT(*) > 1
        )
        ORDER BY sf.id, l.path
        """
    ).fetchall()

    groups: dict[int, DuplicateGroup] = {}
    for row in rows:
        group = groups.setdefault(
            row["id"],
            DuplicateGroup(sha256=row["sha256"], source_file_id=row["id"]),
        )
        group.paths.append(row["path"])
    return list(groups.values())


def locations_for(conn: sqlite3.Connection, source_file_id: int) -> list[str]:
    """Return every path recorded for a source file, ordered by path."""
    rows = conn.execute(
        "SELECT path FROM source_file_location WHERE source_file_id = ? ORDER BY path",
        (source_file_id,),
    ).fetchall()
    return [row["path"] for row in rows]


def format_duplicate_report(groups: list[DuplicateGroup]) -> str:
    """Render duplicate groups as plain text."""
    if not groups:
        return "No duplicate files found."

    lines = [f"{len(groups)} duplicate group(s) found."]
    for group in groups:
        lines.append("")
        lines.append(f"sha256 {group.sha256[:12]}... ({len(group.paths)} locations)")
        lines.extend(f"  - {path}" for path in group.paths)
    return "\n".join(lines)