"""Client for the LLM Gateway (STORY-1.8).

All embedding and generation calls go through this module.

Privacy: prompts, input texts, and gateway error details are never logged
and never appear in exception messages. Some error details can contain model
output (and so document content); they are kept on the exception's `detail`
attribute for callers that store them where document content is allowed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx

from document_store.config import GatewayConfig

log = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({502, 503, 504})
RETRY_BACKOFF_SECONDS = 2.0  # doubled after each failed attempt
HEALTH_TIMEOUT_SECONDS = 5.0
MAX_OUTPUT_RETRIES = 5  # the gateway's upper limit for max_retries


class GatewayError(Exception):
    """A gateway call failed. str() is safe to log; `detail` may not be."""

    def __init__(
        self, message: str, *, status_code: int | None = None, detail: Any = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class GatewayRequestError(GatewayError):
    """The gateway rejected the request (400, or 422 request validation).

    A configuration or caller error: a model outside the allowlist, an
    oversized prompt or batch, or an invalid schema. Not retried.
    """


class GatewayAuthError(GatewayError):
    """The gateway rejected the API key (401). Fatal until the key is corrected."""


class StructuredOutputError(GatewayError):
    """The model did not produce output matching the schema (422).

    An extraction failure for this input. `detail` can contain model output.
    """


class GatewayUnavailableError(GatewayError):
    """The gateway or its backend was unreachable, failed, or timed out
    (502, 503, 504, or a transport error), and retries were exhausted."""


@dataclass(frozen=True)
class EmbedResult:
    embeddings: list[list[float]]
    model: str
    dimensions: int


@dataclass(frozen=True)
class GenerateResult:
    text: str
    model: str


@dataclass(frozen=True)
class StructuredResult:
    data: dict[str, Any]
    model: str
    attempts: int


def _json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _error_detail(response: httpx.Response) -> Any:
    """The gateway's error detail: 'detail' for most errors, 'error' for 401 and 500."""
    body = _json_body(response)
    if isinstance(body, dict):
        return body.get("detail", body.get("error"))
    return None


def _summarise_validation(errors: list[Any]) -> str:
    """Summarise request-validation errors. The gateway strips input values from them."""
    parts = []
    for error in errors:
        if isinstance(error, dict):
            location = ".".join(str(item) for item in error.get("loc") or [])
            parts.append(f"{location}: {error.get('msg')}")
    return "; ".join(parts)


class GatewayClient:
    """Synchronous client for the LLM Gateway. Use as a context manager, or call close()."""

    def __init__(
        self,
        config: GatewayConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=config.url,
            headers={"x-api-key": config.api_key, "x-client-name": config.client_name},
            timeout=config.timeout_seconds,
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # -- Endpoints ------------------------------------------------------------

    def check_health(self) -> None:
        """Confirm the gateway is reachable. Not retried.

        Raises:
            GatewayUnavailableError: if the gateway cannot be reached.
            GatewayError: if it responds, but not with a healthy status.
        """
        try:
            response = self._http.get("/health", timeout=HEALTH_TIMEOUT_SECONDS)
        except httpx.TransportError as exc:
            raise GatewayUnavailableError(
                f"gateway unreachable at {self._config.url}: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200 or _json_body(response) != {"status": "ok"}:
            raise GatewayError(
                f"gateway health check failed (status {response.status_code})",
                status_code=response.status_code,
            )

    def embed(self, texts: Sequence[str], model: str) -> EmbedResult:
        """Embed texts, in order. Large inputs are sent in batches.

        Raises:
            ValueError: if texts is empty.
            GatewayError: see the subclasses for the failure kinds.
        """
        if isinstance(texts, str):
            raise TypeError("texts must be a sequence of strings, not a string")
        if not texts:
            raise ValueError("at least one text is required")

        started = time.monotonic()
        size = self._config.embed_batch_size
        embeddings: list[list[float]] = []
        dimensions: int | None = None
        for start in range(0, len(texts), size):
            batch = list(texts[start : start + size])
            body = self._post("/embed", {"input": batch, "model": model})
            vectors = body.get("embeddings")
            batch_dimensions = body.get("dimensions")
            if (
                not isinstance(vectors, list)
                or len(vectors) != len(batch)
                or not isinstance(batch_dimensions, int)
                or any(
                    not isinstance(vector, list) or len(vector) != batch_dimensions
                    for vector in vectors
                )
            ):
                raise GatewayError("gateway returned malformed embeddings")
            if dimensions is None:
                dimensions = batch_dimensions
            elif batch_dimensions != dimensions:
                raise GatewayError("gateway returned embeddings of inconsistent dimensions")
            embeddings.extend(vectors)

        assert dimensions is not None
        log.debug(
            "embedded %d text(s) model=%s dimensions=%d duration=%.2fs",
            len(texts), model, dimensions, time.monotonic() - started,
        )
        return EmbedResult(embeddings=embeddings, model=model, dimensions=dimensions)

    def generate(
        self,
        prompt: str,
        model: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
    ) -> GenerateResult:
        """Generate free-form text."""
        payload: dict[str, Any] = {"prompt": prompt, "model": model}
        if system is not None:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature

        started = time.monotonic()
        body = self._post("/generate", payload)
        text = body.get("response")
        if not isinstance(text, str):
            raise GatewayError("gateway returned a malformed generate response")
        log.debug("generated model=%s duration=%.2fs", model, time.monotonic() - started)
        return GenerateResult(text=text, model=str(body.get("model", model)))

    def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        model: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        output_retries: int = 2,
    ) -> StructuredResult:
        """Generate a JSON object matching a JSON Schema (top level must be an object).

        output_retries is the number of times the gateway re-prompts the model
        after invalid output. It is separate from transport retries.

        Raises:
            StructuredOutputError: if no valid output was produced.
            GatewayError: see the subclasses for the other failure kinds.
        """
        if not 0 <= output_retries <= MAX_OUTPUT_RETRIES:
            raise ValueError(f"output_retries must be between 0 and {MAX_OUTPUT_RETRIES}")

        payload: dict[str, Any] = {
            "prompt": prompt,
            "schema": schema,
            "model": model,
            "max_retries": output_retries,
        }
        if system is not None:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature

        # The gateway may call the model once per attempt before it answers.
        timeout = self._config.timeout_seconds * (output_retries + 1)
        started = time.monotonic()
        body = self._post("/generate-structured", payload, timeout=timeout)
        data = body.get("data")
        attempts = body.get("attempts")
        if not isinstance(data, dict) or not isinstance(attempts, int):
            raise GatewayError("gateway returned a malformed structured response")
        log.debug(
            "structured generation model=%s attempts=%d duration=%.2fs",
            model, attempts, time.monotonic() - started,
        )
        return StructuredResult(
            data=data, model=str(body.get("model", model)), attempts=attempts
        )

    # -- Transport ------------------------------------------------------------

    def _post(
        self, path: str, payload: dict[str, Any], timeout: float | None = None
    ) -> dict[str, Any]:
        """POST with retries for backend failures. Returns the response body."""
        attempts = self._config.retries + 1
        failure = ""
        status: int | None = None
        detail: Any = None
        for attempt in range(1, attempts + 1):
            try:
                response = self._http.post(
                    path, json=payload, timeout=timeout or self._config.timeout_seconds
                )
            except httpx.TransportError as exc:
                failure, status, detail = type(exc).__name__, None, None
            else:
                if response.status_code not in RETRYABLE_STATUSES:
                    return self._result(path, response)
                status = response.status_code
                failure, detail = f"status {status}", _error_detail(response)

            if attempt < attempts:
                delay = RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1)
                log.warning(
                    "gateway %s failed (%s); retry %d of %d in %.0fs",
                    path, failure, attempt, self._config.retries, delay,
                )
                self._sleep(delay)

        raise GatewayUnavailableError(
            f"gateway {path} unavailable after {attempts} attempt(s): {failure}",
            status_code=status,
            detail=detail,
        )

    def _result(self, path: str, response: httpx.Response) -> dict[str, Any]:
        """Return the body of a successful response, or raise for an error status."""
        status = response.status_code
        if status == 200:
            body = _json_body(response)
            if not isinstance(body, dict):
                raise GatewayError(f"gateway returned a malformed response for {path}")
            return body

        detail = _error_detail(response)
        if status == 401:
            raise GatewayAuthError(
                "gateway rejected the API key (401); check LLM_GATEWAY_KEY",
                status_code=status,
                detail=detail,
            )
        if status == 400:
            reason = detail if isinstance(detail, str) else "no detail"
            raise GatewayRequestError(
                f"gateway rejected the request to {path} (400): {reason}",
                status_code=status,
                detail=detail,
            )
        if status == 422 and isinstance(detail, list):
            raise GatewayRequestError(
                f"gateway rejected the request to {path} (422): "
                f"{_summarise_validation(detail)}",
                status_code=status,
                detail=detail,
            )
        if status == 422:
            # The detail quotes the model's output, so it stays out of the message.
            raise StructuredOutputError(
                "model did not produce valid structured output (422)",
                status_code=status,
                detail=detail,
            )
        raise GatewayError(
            f"gateway returned unexpected status {status} for {path}",
            status_code=status,
            detail=detail,
        )