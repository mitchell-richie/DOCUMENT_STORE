"""Gateway startup check: python -m document_store.gateway_check [--full]

Confirms the gateway is reachable and that the configured models work,
before any processing begins (Architecture, Section 10.4).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from document_store.config import ConfigError, Settings, load_settings
from document_store.gateway import GatewayClient, GatewayError

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_CONFIG_ERROR = 2

SMOKE_TEXT = "gateway smoke test"


@dataclass
class CheckReport:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def run_check(client: GatewayClient, settings: Settings, full: bool = False) -> CheckReport:
    """Run the checks in order, stopping after the first failure.

    Later checks depend on earlier ones: an embedding test is not informative
    if the health check failed.
    """
    report = CheckReport()

    try:
        client.check_health()
    except GatewayError as exc:
        report.failed.append(f"health: {exc}")
        return report
    report.passed.append(f"health: {settings.gateway.url}")

    model = settings.models.embedding
    expected = settings.models.embedding_dimensions
    try:
        result = client.embed([SMOKE_TEXT], model)
    except GatewayError as exc:
        report.failed.append(f"embed ({model}): {exc}")
        return report
    if result.dimensions != expected:
        report.failed.append(
            f"embed ({model}): returned {result.dimensions} dimensions; "
            f"config expects {expected} (models.embedding_dimensions)"
        )
        return report
    report.passed.append(f"embed: {model}, {result.dimensions} dimensions")

    if not full:
        return report

    for purpose, name in (
        ("extraction", settings.models.extraction),
        ("generation", settings.models.generation),
    ):
        try:
            client.generate("Reply with the single word OK.", name, temperature=0.0)
        except GatewayError as exc:
            report.failed.append(f"{purpose} ({name}): {exc}")
            return report
        report.passed.append(f"{purpose}: {name}")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the LLM Gateway and configured models.")
    parser.add_argument("--config", type=Path, default=Path("config/config.toml"))
    parser.add_argument(
        "--full",
        action="store_true",
        help="also test the extraction and generation models (loads them; slow)",
    )
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    with GatewayClient(settings.gateway) as client:
        report = run_check(client, settings, full=args.full)

    for line in report.passed:
        print(f"ok    {line}")
    for line in report.failed:
        print(f"FAIL  {line}", file=sys.stderr)
    return EXIT_OK if report.ok else EXIT_CHECK_FAILED


if __name__ == "__main__":
    sys.exit(main())