"""Tests for the gateway startup check."""

from pathlib import Path
from typing import Any

import httpx
from document_store.gateway_check import run_check

from conftest import FakeGateway, _embed_reply
from document_store.config import (
    ClassificationConfig,
    GatewayConfig,
    Models,
    Paths,
    RoutingConfig,
    Settings,
)
from document_store.gateway import GatewayClient


def _settings(dimensions: int = 2) -> Settings:
    return Settings(
        paths=Paths(
            project_dir=Path("."), database=Path("case.sqlite"), originals=Path("originals"),
            cache=Path("cache"), logs=Path("logs"),
        ),
        gateway=GatewayConfig(url="http://gateway.test", client_name="case-dms", api_key="k"),
        models=Models(
            embedding="bge-m3",
            embedding_dimensions=dimensions,
            extraction="qwen2.5:7b-instruct",
            generation="qwen2.5:7b-instruct",
        ),
        chunk_max_chars=2000,
        chunk_overlap_chars=200,
        ocr_confidence_threshold=0.6,
        ocr_min_text_chars=20,
        ocr_dpi=200,
        classification=ClassificationConfig(rules=(), default_doc_class="unclassified"),
        routing=RoutingConfig(mapping={}),
    )


def _client(gateway: Any) -> GatewayClient:
    return GatewayClient(_settings().gateway, transport=httpx.MockTransport(gateway))


def test_health_and_embed_pass() -> None:
    gateway = FakeGateway((200, {"status": "ok"}),_embed_reply([[0.1, 0.2]]))

    report = run_check(_client(gateway), _settings(dimensions=2))

    assert report.ok
    assert [r.url.path for r in gateway.requests] == ["/health", "/embed"]


def test_unreachable_gateway_stops_at_health() -> None:
    gateway = FakeGateway(httpx.ConnectError("refused"))

    report = run_check(_client(gateway), _settings())

    assert report.failed and report.failed[0].startswith("health:")
    assert len(gateway.requests) == 1


def test_dimension_mismatch_fails() -> None:
    gateway = FakeGateway((200, {"status": "ok"}),_embed_reply([[0.1, 0.2]]))

    report = run_check(_client(gateway), _settings(dimensions=1024))

    assert not report.ok
    assert "config expects 1024" in report.failed[0]


def test_full_check_tests_generation_models() -> None:
    gateway = FakeGateway(
        (200, {"status": "ok"}),
       _embed_reply([[0.1, 0.2]]),
        (200, {"response": "OK", "model": "qwen2.5:7b-instruct"}),
    )

    report = run_check(_client(gateway), _settings(), full=True)

    assert report.ok
    assert len(gateway.requests) == 4  # health, embed, extraction, generation


def test_disallowed_model_reported_in_full_check() -> None:
    gateway = FakeGateway(
        (200, {"status": "ok"}),
       _embed_reply([[0.1, 0.2]]),
        (400, {"detail": "Model 'qwen2.5:7b-instruct' not in allowlist: ['llama3.2']"}),
    )

    report = run_check(_client(gateway), _settings(), full=True)

    assert not report.ok
    assert report.failed[0].startswith("extraction (qwen2.5:7b-instruct)")