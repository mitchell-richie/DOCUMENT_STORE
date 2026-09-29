"""Tests for file registration (STORY-2.1)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from document_store.ingest.register import (
    UnsupportedFileError,
    register_file,
    register_folder,
    sha256_of,
)


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_sha256_matches_known_value(tmp_path: Path) -> None:
    path = tmp_path / "abc.bin"
    path.write_bytes(b"abc")
    assert sha256_of(path) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_register_creates_record(conn: sqlite3.Connection, fixtures_dir: Path) -> None:
    result = register_file(conn, fixtures_dir / "native.pdf")

    assert result.created is True
    row = conn.execute(
        "SELECT sha256, size_bytes, mime_type FROM source_file WHERE id = ?",
        (result.source_file_id,),
    ).fetchone()
    assert row["mime_type"] == "application/pdf"
    assert row["size_bytes"] == (fixtures_dir / "native.pdf").stat().st_size
    assert row["sha256"] == sha256_of(fixtures_dir / "native.pdf")


def test_reregistering_is_idempotent(conn: sqlite3.Connection, fixtures_dir: Path) -> None:
    first = register_file(conn, fixtures_dir / "native.pdf")
    second = register_file(conn, fixtures_dir / "native.pdf")

    assert second.source_file_id == first.source_file_id
    assert second.created is False
    assert _count(conn, "source_file") == 1
    assert _count(conn, "source_file_location") == 1


def test_original_is_unchanged(conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path) -> None:
    original = tmp_path / "native.pdf"
    shutil.copy(fixtures_dir / "native.pdf", original)
    before_bytes = original.read_bytes()
    before_mtime = original.stat().st_mtime_ns

    register_file(conn, original)

    assert original.read_bytes() == before_bytes
    assert original.stat().st_mtime_ns == before_mtime


def test_identical_content_at_two_paths_yields_one_file(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    copy_a = tmp_path / "a" / "native.pdf"
    copy_b = tmp_path / "b" / "native.pdf"
    for target in (copy_a, copy_b):
        target.parent.mkdir()
        shutil.copy(fixtures_dir / "native.pdf", target)

    register_file(conn, copy_a)
    register_file(conn, copy_b)

    assert _count(conn, "source_file") == 1
    assert _count(conn, "source_file_location") == 2


def test_unsupported_type_raises(conn: sqlite3.Connection, tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("not a supported type", encoding="utf-8")

    with pytest.raises(UnsupportedFileError):
        register_file(conn, notes)


def test_folder_registration_summary(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    folder = tmp_path / "originals"
    folder.mkdir()
    shutil.copy(fixtures_dir / "native.pdf", folder / "native.pdf")
    shutil.copy(fixtures_dir / "sample.docx", folder / "sample.docx")
    (folder / "notes.txt").write_text("skip me", encoding="utf-8")

    summary = register_folder(conn, folder)

    assert summary.registered == 2
    assert summary.existing == 0
    assert [p.name for p in summary.skipped] == ["notes.txt"]


def test_folder_rerun_creates_nothing(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    folder = tmp_path / "originals"
    folder.mkdir()
    shutil.copy(fixtures_dir / "native.pdf", folder / "native.pdf")

    register_folder(conn, folder)
    summary = register_folder(conn, folder)

    assert summary.registered == 0
    assert summary.existing == 1
    assert _count(conn, "source_file") == 1