"""Tests for the LLM Gateway client (STORY-1.8)."""

import json
import logging

import httpx
import pytest

from conftest import FakeGateway, _client, _embed_reply
from document_store.config import ConfigError, GatewayConfig
from document_store.gateway import (
    GatewayAuthError,
    GatewayError,
    GatewayRequestError,
    GatewayUnavailableError,
    StructuredOutputError,
)

SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}}


# --- Successful calls --------------------------------------------------------


def test_health_ok() -> None:
    gateway = FakeGateway((200, {"status": "ok"}))
    client, _ = _client(gateway)
    client.check_health()
    assert gateway.requests[0].url.path == "/health"


def test_requests_carry_key_and_client_name() -> None:
    gateway = FakeGateway(_embed_reply([[0.1, 0.2]]))
    client, _ = _client(gateway)

    client.embed(["one"], "bge-m3")

    headers = gateway.requests[0].headers
    assert headers["x-api-key"] == "secret-key"
    assert headers["x-client-name"] == "case-dms"


def test_embed_returns_vectors_and_dimensions() -> None:
    gateway = FakeGateway(_embed_reply([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]))
    client, _ = _client(gateway)

    result = client.embed(["one", "two"], "bge-m3")

    assert result.embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert result.dimensions == 3
    assert gateway.payload() == {"input": ["one", "two"], "model": "bge-m3"}


def test_embed_batches_and_preserves_order() -> None:
    batches: list[list[str]] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        batches.append(texts)
        vectors = [[float(len(text)), 0.0] for text in texts]
        return httpx.Response(
            200, json={"embeddings": vectors, "model": "bge-m3", "dimensions": 2}
        )

    client, _ = _client(gateway, embed_batch_size=2)

    result = client.embed(["a", "bb", "ccc", "dddd", "eeeee"], "bge-m3")

    assert batches == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    assert [vector[0] for vector in result.embeddings] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_embed_rejects_empty_input() -> None:
    client, _ = _client(FakeGateway(_embed_reply([[0.1]])))
    with pytest.raises(ValueError, match="at least one"):
        client.embed([], "bge-m3")


def test_embed_rejects_wrong_vector_count() -> None:
    client, _ = _client(FakeGateway(_embed_reply([[0.1, 0.2]])))
    with pytest.raises(GatewayError, match="malformed"):
        client.embed(["one", "two"], "bge-m3")


def test_generate_returns_text_and_omits_unset_options() -> None:
    gateway = FakeGateway((200, {"response": "An answer.", "model": "qwen2.5:7b-instruct"}))
    client, _ = _client(gateway)

    result = client.generate("A question?", "qwen2.5:7b-instruct")

    assert result.text == "An answer."
    assert gateway.payload() == {"prompt": "A question?", "model": "qwen2.5:7b-instruct"}


def test_generate_structured_sends_schema_and_returns_data() -> None:
    gateway = FakeGateway(
        (200, {"data": {"name": "A. Person"}, "model": "qwen2.5:7b-instruct", "attempts": 2})
    )
    client, _ = _client(gateway)

    result = client.generate_structured(
        "Extract the name.", SCHEMA, "qwen2.5:7b-instruct", temperature=0.0, output_retries=1
    )

    assert result.data == {"name": "A. Person"}
    assert result.attempts == 2
    assert gateway.payload() == {
        "prompt": "Extract the name.",
        "schema": SCHEMA,
        "model": "qwen2.5:7b-instruct",
        "max_retries": 1,
        "temperature": 0.0,
    }


# --- Errors ------------------------------------------------------------------


def test_400_is_a_request_error_and_not_retried() -> None:
    gateway = FakeGateway((400, {"detail": "Model 'x' not in allowlist: ['llama3.2']"}))
    client, sleeps = _client(gateway)

    with pytest.raises(GatewayRequestError, match="not in allowlist"):
        client.generate("A question?", "x")

    assert len(gateway.requests) == 1
    assert sleeps == []


def test_401_is_an_auth_error_and_not_retried() -> None:
    gateway = FakeGateway((401, {"error": "unauthorized"}))
    client, _ = _client(gateway)

    with pytest.raises(GatewayAuthError, match="LLM_GATEWAY_KEY"):
        client.embed(["one"], "bge-m3")

    assert len(gateway.requests) == 1


def test_422_request_validation_is_a_request_error() -> None:
    detail = [
        {
            "type": "string_too_long",
            "loc": ["body", "prompt"],
            "msg": "String should have at most 10000 characters",
        }
    ]
    client, _ = _client(FakeGateway((422, {"detail": detail})))

    with pytest.raises(GatewayRequestError, match="body.prompt: String should have at most"):
        client.generate("x" * 20000, "qwen2.5:7b-instruct")


def test_422_invalid_output_is_a_structured_output_error() -> None:
    detail = "Model failed to produce valid structured output after 3 attempts. Last error: ..."
    gateway = FakeGateway((422, {"detail": detail}))
    client, _ = _client(gateway)

    with pytest.raises(StructuredOutputError) as caught:
        client.generate_structured("Extract the name.", SCHEMA, "qwen2.5:7b-instruct")

    assert caught.value.detail == detail
    assert len(gateway.requests) == 1


def test_backend_failure_is_retried_then_succeeds() -> None:
    gateway = FakeGateway(
        (503, {"detail": "LLM backend unreachable"}), _embed_reply([[0.1, 0.2]])
    )
    client, sleeps = _client(gateway)

    result = client.embed(["one"], "bge-m3")

    assert result.dimensions == 2
    assert len(gateway.requests) == 2
    assert sleeps == [2.0]


def test_backend_failure_exhausts_retries() -> None:
    gateway = FakeGateway((504, {"detail": "LLM backend timed out"}))
    client, sleeps = _client(gateway, retries=2)

    with pytest.raises(GatewayUnavailableError, match="after 3 attempt") as caught:
        client.embed(["one"], "bge-m3")

    assert caught.value.status_code == 504
    assert len(gateway.requests) == 3
    assert sleeps == [2.0, 4.0]


def test_connection_failure_is_retried() -> None:
    gateway = FakeGateway(httpx.ConnectError("connection refused"))
    client, _ = _client(gateway, retries=1)

    with pytest.raises(GatewayUnavailableError, match="ConnectError"):
        client.embed(["one"], "bge-m3")

    assert len(gateway.requests) == 2


def test_500_is_not_retried() -> None:
    gateway = FakeGateway((500, {"error": "Internal server error"}))
    client, sleeps = _client(gateway)

    with pytest.raises(GatewayError, match="unexpected status 500") as caught:
        client.generate("A question?", "qwen2.5:7b-instruct")

    assert not isinstance(caught.value, GatewayUnavailableError)
    assert len(gateway.requests) == 1
    assert sleeps == []


def test_health_failure_when_unreachable() -> None:
    client, _ = _client(FakeGateway(httpx.ConnectError("connection refused")))
    with pytest.raises(GatewayUnavailableError, match="unreachable"):
        client.check_health()


# --- Privacy and configuration -------------------------------------------------


def test_prompt_and_error_detail_stay_out_of_messages_and_logs(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    detail = "Last error: 'THE CONFIDENTIAL PASSAGE' is not of type 'object'"
    client, _ = _client(FakeGateway((422, {"detail": detail})))

    with pytest.raises(StructuredOutputError) as caught:
        client.generate_structured(
            "Summarise: THE CONFIDENTIAL PASSAGE", SCHEMA, "qwen2.5:7b-instruct"
        )

    assert "CONFIDENTIAL" not in str(caught.value)
    assert "CONFIDENTIAL" not in caplog.text
    assert "secret-key" not in caplog.text


def test_api_key_is_not_in_config_repr() -> None:
    config = GatewayConfig(url="http://gateway.test", client_name="case-dms", api_key="secret-key")
    assert "secret-key" not in repr(config)


def test_invalid_gateway_settings_rejected() -> None:
    with pytest.raises(ConfigError, match="embed_batch_size"):
        GatewayConfig(
            url="http://gateway.test", client_name="case-dms", api_key="k", embed_batch_size=0
        )