"""Shared fixtures."""

import json
import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from document_store.config import ClassificationConfig, ClassificationRule, RoutingConfig
from document_store.db.connection import connect
from document_store.db.migrate import migrate
from document_store.extract.ocr import PADDLE_ENGINE, OcrCache
from document_store.extract.pdf import extract_pdf
from document_store.gateway import GatewayClient, GatewayConfig
from document_store.ingest.classify import Classifier, build_classifier
from document_store.ingest.documents import create_or_update_document
from document_store.ingest.register import register_file, sha256_of
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

LOW_CONFIDENCE_TEXT = "Smudged words from a poor scan"

CONFIG_TEMPLATE = """
[paths]
project_dir = "{project_dir}"
database = "case.sqlite"
originals = "originals"
cache = "cache"
logs = "logs"

[gateway]
url = "http://llm-gateway-api:8000"
client_name = "case-dms"

[models]
embedding = "bge-m3"
embedding_dimensions = 1024
extraction = "qwen2.5:7b-instruct"
generation = "qwen2.5:7b-instruct"

[chunking]
max_chars = 2000
overlap_chars = 200

[ocr]
confidence_threshold = 0.6
min_text_chars = 20
dpi = 200

[classification]
default_doc_class = "unclassified"

[routing]
in_camera = "local_only"
financial_statement = "external"
receipt = "standard"
court_filing = "standard"
correspondence = "standard"
other = "standard"
unclassified = "local_only"
"""


class NoEngine:
    """Fails if OCR is attempted: tests read OCR results from a seeded cache."""

    def predict(self, input: str) -> None:
        raise AssertionError("OCR engine should not run; the result is cached")


@dataclass(frozen=True)
class LowConfidenceScan:
    document_id: int
    path: Path
    sha256: str
    pages: list[int]
    cache: OcrCache


def seed_ocr_cache(
    cache: OcrCache,
    sha256: str,
    pages: list[int],
    text: str = LOW_CONFIDENCE_TEXT,
    confidence: float = 0.31,
) -> None:
    """Write a cached OCR result for each page, as if OCR had already run."""
    for number in pages:
        cache.path_for(sha256, number).write_text(
            json.dumps({"text": text, "mean_confidence": confidence, "engine": PADDLE_ENGINE}),
            encoding="utf-8",
        )


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A valid config file whose project directory is tmp_path."""
    monkeypatch.setenv("LLM_GATEWAY_KEY", "test-key")
    path = tmp_path / "config.toml"
    path.write_text(CONFIG_TEMPLATE.format(project_dir=tmp_path.as_posix()), encoding="utf-8")
    return path


@pytest.fixture
def low_confidence_scan(
    conn: sqlite3.Connection, fixtures_dir: Path, tmp_path: Path
) -> LowConfidenceScan:
    """The scanned fixture as a registered document, with a cached
    low-confidence OCR result for each image-only page."""
    path = (fixtures_dir / "scanned.pdf").resolve()
    source = register_file(conn, path).source_file_id
    document_id = create_or_update_document(
        conn, source, "correspondence", "standard", "scanned.pdf"
    ).document_id
    sha256 = sha256_of(path)
    pages = extract_pdf(path).pages_needing_ocr
    assert pages, "scanned.pdf should have at least one image-only page"

    cache = OcrCache(tmp_path / "cache")
    seed_ocr_cache(cache, sha256, pages)
    return LowConfidenceScan(document_id, path, sha256, pages, cache)


class FakeGateway:
    """Replies from a list, repeating the last reply, and records requests.

    A reply is (status, json_body) or an exception to raise.
    """

    def __init__(self, *replies: Any) -> None:
        self.replies = replies
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies[min(len(self.requests), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx.Response(status, json=body)

    def payload(self, index: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def _client(gateway: Any, **overrides: Any) -> tuple[GatewayClient, list[float]]:
    sleeps: list[float] = []
    config = GatewayConfig(
        url="http://gateway.test", client_name="case-dms", api_key="secret-key", **overrides
    )
    client = GatewayClient(config, transport=httpx.MockTransport(gateway), sleep=sleeps.append)
    return client, sleeps


def _embed_reply(vectors: list[list[float]]) -> tuple[int, dict[str, Any]]:
    return 200, {"embeddings": vectors, "model": "bge-m3", "dimensions": len(vectors[0])}