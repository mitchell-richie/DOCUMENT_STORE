"""Guards against drift between route definitions and the database schema."""

import sqlite3

from document_store.constants import DOC_CLASSES, PROCESSING_ROUTES, ROUTE_RESTRICTIVENESS


def test_ranks_are_unique() -> None:
    # Equal ranks would make "most restrictive" ambiguous.
    values = list(ROUTE_RESTRICTIVENESS.values())
    assert len(values) == len(set(values))


def test_every_route_has_a_rank() -> None:
    assert set(ROUTE_RESTRICTIVENESS) == set(PROCESSING_ROUTES)


def test_schema_route_checks_match_constants(conn: sqlite3.Connection) -> None:
    # The document table's CHECK constraint must list exactly the known routes.
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'document'"
    ).fetchone()["sql"]
    for route in PROCESSING_ROUTES:
        assert f"'{route}'" in sql


def test_schema_doc_class_checks_match_constants(conn: sqlite3.Connection) -> None:
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'document'"
    ).fetchone()["sql"]
    for doc_class in DOC_CLASSES:
        assert f"'{doc_class}'" in sql