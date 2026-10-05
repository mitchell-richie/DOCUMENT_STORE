"""Configuration loading for case-dms.

Settings are read from config.toml. Secrets are read from environment
variables only and are never written to the configuration file.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config/config.toml")


class ConfigError(RuntimeError):
    """Raised when configuration is missing or malformed."""


@dataclass(frozen=True)
class Paths:
    project_dir: Path
    database: Path
    originals: Path
    cache: Path
    logs: Path


@dataclass(frozen=True)
class GatewayConfig:
    url: str
    client_name: str
    api_key: str


@dataclass(frozen=True)
class Models:
    embedding: str
    embedding_dimensions: int
    extraction: str
    generation: str


@dataclass(frozen=True)
class Settings:
    paths: Paths
    gateway: GatewayConfig
    models: Models
    chunk_max_chars: int
    chunk_overlap_chars: int
    ocr_confidence_threshold: float
    ocr_min_text_chars: int
    classification: ClassificationConfig
    routing: RoutingConfig


def load_settings(path: Path = DEFAULT_CONFIG_PATH) -> Settings:
    """Load settings from a TOML file and environment variables.

    Raises:
        ConfigError: if the file is missing, malformed, or a required
            environment variable is not set.
    """
    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Malformed configuration file {path}: {exc}") from exc

    try:
        paths_raw = raw["paths"]
        gateway_raw = raw["gateway"]
        models_raw = raw["models"]
        chunking_raw = raw["chunking"]
        ocr_raw = raw["ocr"]
        classification_raw = raw["classification"]
    except KeyError as exc:
        raise ConfigError(f"Missing configuration section: {exc.args[0]}") from exc

    api_key = os.environ.get("LLM_GATEWAY_KEY", "")
    if not api_key:
        raise ConfigError("LLM_GATEWAY_KEY environment variable is not set")

    project_dir = Path(paths_raw["project_dir"]).resolve()

    classification = ClassificationConfig(
        rules=tuple(
            ClassificationRule(doc_class=r["doc_class"], pattern=r["pattern"])
            for r in classification_raw.get("rules", [])
        ),
        default_doc_class=classification_raw["default_doc_class"],
    )

    try:
        routing_raw = raw['routing']
    except KeyError as exc:
        raise ConfigError(f"Missing configuration section: {exc.args[0]}") from exc
    routing=RoutingConfig(mapping=dict(routing_raw))

    return Settings(
        paths=Paths(
            project_dir=project_dir,
            database=project_dir / paths_raw["database"],
            originals=project_dir / paths_raw["originals"],
            cache=project_dir / paths_raw["cache"],
            logs=project_dir / paths_raw["logs"],
        ),
        gateway=GatewayConfig(
            url=gateway_raw["url"],
            client_name=gateway_raw["client_name"],
            api_key=api_key,
        ),
        models=Models(
            embedding=models_raw["embedding"],
            embedding_dimensions=int(models_raw["embedding_dimensions"]),
            extraction=models_raw["extraction"],
            generation=models_raw["generation"],
        ),
        chunk_max_chars=int(chunking_raw["max_chars"]),
        chunk_overlap_chars=int(chunking_raw["overlap_chars"]),
        ocr_confidence_threshold=float(ocr_raw["confidence_threshold"]),
        ocr_min_text_chars=int(ocr_raw["min_text_chars"]),
        classification=classification,
        routing=routing,
    )


@dataclass(frozen=True)
class ClassificationRule:
    doc_class: str
    pattern: str


@dataclass(frozen=True)
class ClassificationConfig:
    rules: tuple[ClassificationRule, ...]
    default_doc_class: str


@dataclass(frozen=True)
class RoutingConfig:
    mapping: dict[str, str]