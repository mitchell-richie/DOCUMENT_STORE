"""File registration: hash, identify type, and record in source_file.

Originals are opened read-only. They are never copied, renamed, or modified.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

HASH_BLOCK_SIZE = 1024 * 1024

SUPPORTED_MIME_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".eml": "message/rfc822",
    ".mbox": "application/mbox",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


class UnsupportedFileError(ValueError):
    """Raised when a file's extension is not in SUPPORTED_MIME_TYPES."""


@dataclass(frozen=True)
class RegisterResult:
    source_file_id: int
    created: bool          # True if the content was not previously registered
    location_created: bool  # True if this path was not previously recorded


@dataclass
class FolderSummary:
    registered: int = 0     # new content
    existing: int = 0       # content already registered at this path
    new_locations: int = 0  # content already registered, but at a new path
    skipped: list[Path] = field(default_factory=list)


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 digest of a file, read in blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(HASH_BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def mime_type_for(path: Path) -> str | None:
    """Return the MIME type for a supported file, or None if unsupported."""
    return SUPPORTED_MIME_TYPES.get(path.suffix.lower())


def register_file(
    conn: sqlite3.Connection,
    path: Path,
    now: datetime | None = None,
) -> RegisterResult:
    """Record a file in source_file and source_file_location.

    A file whose content is already registered is not duplicated. Its path is
    recorded as an additional location if not already present.

    Raises:
        UnsupportedFileError: if the extension is not supported.
        FileNotFoundError: if the file does not exist.
    """
    path = path.resolve()
    mime = mime_type_for(path)
    if mime is None:
        raise UnsupportedFileError(f"unsupported file type: {path.name}")

    digest = sha256_of(path)
    size = path.stat().st_size
    timestamp = (now or datetime.now(UTC)).isoformat()

    with conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO source_file (sha256, size_bytes, mime_type, imported_at) "
            "VALUES (?, ?, ?, ?)",
            (digest, size, mime, timestamp),
        )
        created = cursor.rowcount == 1
        file_id = conn.execute(
            "SELECT id FROM source_file WHERE sha256 = ?", (digest,)
        ).fetchone()["id"]
        location_cursor = conn.execute(
            "INSERT OR IGNORE INTO source_file_location (source_file_id, path, first_seen_at) "
            "VALUES (?, ?, ?)",
            (file_id, str(path), timestamp),
        )
        location_created = location_cursor.rowcount == 1

    return RegisterResult(
        source_file_id=file_id,
        created=created,
        location_created=location_created,
    )


def register_folder(conn: sqlite3.Connection, root: Path) -> FolderSummary:
    """Register every supported file beneath a folder. Unsupported files are skipped."""
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {root}")

    summary = FolderSummary()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if mime_type_for(path) is None:
            log.info("skipping unsupported file: %s", path.name)
            summary.skipped.append(path)
            continue
        result = register_file(conn, path)
        if result.created:
            summary.registered += 1
        elif result.location_created:
            summary.new_locations += 1
        else:
            summary.existing += 1
    return summary