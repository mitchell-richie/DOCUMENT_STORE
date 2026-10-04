"""Shared fixtures."""

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from document_store.config import ClassificationConfig, ClassificationRule, RoutingConfig
from document_store.db.connection import connect
from document_store.db.migrate import migrate
from document_store.ingest.classify import Classifier, build_classifier
from document_store.ingest.routing import Router, build_router

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

@pytest.fixture
def fixtures_dir() -> Path:
    "Directory containing synthetic test fixtures"
    return FIXTURES_DIR


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated database with sqlite-vec loaded."""
    connection = connect(tmp_path / "test.sqlite")
    migrate(connection)
    yield connection
    connection.close()

ROUTING = {
    "in_camera": "local_only",
    "financial_statement": "external",
    "receipt": "standard",
    "court_filing": "standard",
    "correspondence": "standard",
    "other": "standard",
    "unclassified": "local_only",
}

@pytest.fixture
def router() -> Router:
    return build_router(RoutingConfig(mapping=ROUTING))

@pytest.fixture
def classifier() -> Classifier:
    return build_classifier(
        ClassificationConfig(
            rules=(
                ClassificationRule(doc_class="in_camera", pattern="in_camera/**"),
                ClassificationRule(doc_class="correspondence", pattern="correspondence/**"),
                ClassificationRule(doc_class="financial_statement", pattern="**/bank_statement*"),
            ),
            default_doc_class="other",
        )
    )

@pytest.fixture
def originals(tmp_path: Path, fixtures_dir: Path) -> Path:
    root = tmp_path / "originals"
    (root / "in_camera").mkdir(parents=True)
    (root / "correspondence").mkdir()
    shutil.copy(fixtures_dir / "native.pdf", root / "in_camera" / "order.pdf")
    shutil.copy(fixtures_dir / "sample.docx", root / "correspondence" / "letter.docx")
    (root / "correspondence" / "notes.txt").write_text("skip", encoding="utf-8")
    return root

def insert_chunk(conn: sqlite3.Connection, text: str, ordinal: int = 0) -> int:
    """Insert a chunk under a shared test document and return its ID."""
    conn.execute(
        "INSERT OR IGNORE INTO source_file (id, sha256, size_bytes, imported_at) "
        "VALUES (1, 'test-hash', 1, '2025-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO document (id, source_file_id, doc_class, processing_route, created_at) "
        "VALUES (1, 1, 'other', 'standard', '2025-01-01T00:00:00+00:00')"
    )
    cursor = conn.execute(
        "INSERT INTO chunk (document_id, ordinal, text, char_start, char_end, chunk_method) "
        "VALUES (1, ?, ?, 0, ?, 'test')",
        (ordinal, text, len(text)),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid