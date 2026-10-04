"""Logging setup shared across the application.

Modules obtain loggers with logging.getLogger(__name__). Entry points call
configure_console() once, for human-readable text on the console. Long-
running operations use run_log_file() to write a per-run log under the logs
folder, as JSON lines, one record per line, for machine-readable review.

Privacy rule: log file names, counts, identifiers, and timings only.
Never log document text, quotations, or extracted content.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_CONSOLE_MARKER = "_document_store_console"


class JsonLogFormatter(logging.Formatter):
    """Render one JSON object per line: time, level, logger, message, and
    exception text if present."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


def configure_console(level: int = logging.INFO) -> None:
    """Attach one text console handler to the root logger. Safe to call repeatedly."""
    root = logging.getLogger()
    root.setLevel(min(root.level or level, level))
    if not any(getattr(h, _CONSOLE_MARKER, False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(TEXT_FORMAT))
        setattr(handler, _CONSOLE_MARKER, True)
        root.addHandler(handler)


@contextmanager
def run_log_file(
    logs_dir: Path,
    name: str,
    stamp: str,
    level: int = logging.INFO,
) -> Generator[Path]:
    """Write JSON-line records at `level` and above to
    logs_dir/<name>-<stamp>.log. The root logger level is restored when the
    block exits.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{name}-{stamp}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(JsonLogFormatter())

    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(min(previous_level or level, level))
    root.addHandler(handler)
    try:
        yield path
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(previous_level)