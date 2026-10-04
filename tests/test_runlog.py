"""Tests for the ingestion run log (STORY-2.7)."""

import json
import sqlite3

from document_store.ingest.runlog import finish_run, start_run


def _run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM processing_run WHERE id = ?", (run_id,)).fetchone()


def test_start_run_records_stage_parameters_and_start_time(conn: sqlite3.Connection) -> None:
    run_id = start_run(conn, "ingest", {"root": "/x"}, now="2025-01-01T00:00:00+00:00")

    row = _run(conn, run_id)
    assert row["stage"] == "ingest"
    assert json.loads(row["parameters"]) == {"root": "/x"}
    assert row["started_at"] == "2025-01-01T00:00:00+00:00"
    assert row["finished_at"] is None


def test_finish_run_sets_end_time_and_merges_summary(conn: sqlite3.Connection) -> None:
    run_id = start_run(conn, "ingest", {"root": "/x"}, now="2025-01-01T00:00:00+00:00")
    finish_run(conn, run_id, {"documents_created": 3}, now="2025-01-01T00:01:00+00:00")

    row = _run(conn, run_id)
    assert row["finished_at"] == "2025-01-01T00:01:00+00:00"
    parameters = json.loads(row["parameters"])
    assert parameters["root"] == "/x"
    assert parameters["summary"] == {"documents_created": 3}


def test_finish_unknown_run_raises(conn: sqlite3.Connection) -> None:
    import pytest

    with pytest.raises(ValueError):
        finish_run(conn, 999, {})