"""Tests for duplicate detection (STORY-2.2)."""

import shutil
import sqlite3
from pathlib import Path

from document_store.ingest.duplicates import (
    find_duplicates,
    format_duplicate_report,
    locations_for,
)
from document_store.ingest.register import register_file, register_folder


def _copy_to(folder: Path, source: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    shutil.copy(source, target)
    return target


def test_identical_files_in_two_folders_are_one_source_file(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    a = _copy_to(tmp_path / "a", fixtures_dir / "native.pdf")
    b = _copy_to(tmp_path / "b", fixtures_dir / "native.pdf")

    first = register_file(conn, a)
    second = register_file(conn, b)

    assert second.source_file_id == first.source_file_id
    assert second.created is False
    assert second.location_created is True


def test_duplicate_group_lists_all_paths(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    a = _copy_to(tmp_path / "a", fixtures_dir / "native.pdf")
    b = _copy_to(tmp_path / "b", fixtures_dir / "native.pdf")
    register_file(conn, a)
    register_file(conn, b)

    groups = find_duplicates(conn)

    assert len(groups) == 1
    assert groups[0].paths == sorted([str(a.resolve()), str(b.resolve())])


def test_unique_files_are_not_reported(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    register_file(conn, _copy_to(tmp_path / "a", fixtures_dir / "native.pdf"))
    register_file(conn, _copy_to(tmp_path / "a", fixtures_dir / "sample.docx"))

    assert find_duplicates(conn) == []


def test_same_path_reregistered_is_not_a_duplicate(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    path = _copy_to(tmp_path / "a", fixtures_dir / "native.pdf")
    register_file(conn, path)
    register_file(conn, path)

    assert find_duplicates(conn) == []


def test_locations_for_returns_every_path(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    a = _copy_to(tmp_path / "a", fixtures_dir / "native.pdf")
    b = _copy_to(tmp_path / "b", fixtures_dir / "native.pdf")
    result = register_file(conn, a)
    register_file(conn, b)

    assert locations_for(conn, result.source_file_id) == sorted(
        [str(a.resolve()), str(b.resolve())]
    )


def test_report_text_names_every_path(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    a = _copy_to(tmp_path / "a", fixtures_dir / "native.pdf")
    b = _copy_to(tmp_path / "b", fixtures_dir / "native.pdf")
    register_file(conn, a)
    register_file(conn, b)

    report = format_duplicate_report(find_duplicates(conn))

    assert "1 duplicate group(s) found." in report
    assert str(a.resolve()) in report
    assert str(b.resolve()) in report


def test_empty_report_when_no_duplicates(conn: sqlite3.Connection) -> None:
    assert format_duplicate_report(find_duplicates(conn)) == "No duplicate files found."


def test_folder_summary_counts_new_locations(
    conn: sqlite3.Connection, tmp_path: Path, fixtures_dir: Path
) -> None:
    register_folder(conn, _copy_root(tmp_path / "a", fixtures_dir / "native.pdf"))
    summary = register_folder(conn, _copy_root(tmp_path / "b", fixtures_dir / "native.pdf"))

    assert summary.registered == 0
    assert summary.new_locations == 1
    assert summary.existing == 0


def _copy_root(folder: Path, source: Path) -> Path:
    """Return a folder containing one copy of source (for register_folder)."""
    _copy_to(folder, source)
    return folder