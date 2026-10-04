"""Run log: record each ingestion run in processing_run."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def start_run(
    conn: sqlite3.Connection,
    stage: str,
    parameters: dict[str, Any],
    model_id: str | None = None,
    now: str | None = None,
) -> int:
    """Insert a processing_run row with finished_at unset. Returns its ID."""
    with conn:
        cursor = conn.execute(
            "INSERT INTO processing_run (stage, model_id, parameters, started_at) "
            "VALUES (?, ?, ?, ?)",
            (stage, model_id, json.dumps(parameters, sort_keys=True), now or _now()),
        )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    summary: dict[str, Any],
    now: str | None = None,
) -> None:
    """Mark a run complete and merge its summary into the parameters."""
    with conn:
        row = conn.execute(
            "SELECT parameters FROM processing_run WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No processing_run with id {run_id}")

        parameters = json.loads(row["parameters"] or "{}")
        parameters["summary"] = summary
        conn.execute(
            "UPDATE processing_run SET parameters = ?, finished_at = ? WHERE id = ?",
            (json.dumps(parameters, sort_keys=True), now or _now(), run_id),
        )