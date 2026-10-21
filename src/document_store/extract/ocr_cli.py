"""Command-line OCR run: python -m document_store.extract.ocr_cli"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from document_store.config import ConfigError, load_settings
from document_store.db.connection import connect
from document_store.db.migrate import migrate
from document_store.extract.ocr import OcrCache
from document_store.extract.ocr_pipeline import ocr_documents
from document_store.ingest.runlog import finish_run, start_run
from document_store.logs import configure_console, run_log_file
from document_store.ocr.paddle import create_engine

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FILE_ERRORS = 1
EXIT_CONFIG_ERROR = 2
EXIT_UNEXPECTED = 3


class LazyEngine:
    """Creates the OCR engine on first use.

    Loading the models takes time, and a run served entirely from the OCR
    cache never needs them.
    """

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._engine: Any = None

    def predict(self, input: str) -> Any:
        if self._engine is None:
            log.info("loading OCR models")
            self._engine = self._factory()
        return self._engine.predict(input)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OCR registered documents and flag low-confidence pages."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/config.toml"),
        help="configuration file (default: config/config.toml)",
    )
    args = parser.parse_args(argv)

    configure_console()

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    cache = OcrCache(settings.paths.cache, dpi=settings.ocr_dpi)
    engine = LazyEngine(lambda: create_engine())

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with run_log_file(settings.paths.logs, "ocr", stamp) as log_path:
        conn = connect(settings.paths.database)
        try:
            migrate(conn)
            run_id = start_run(
                conn,
                stage="ocr",
                model_id=cache.engine_tag,
                parameters={
                    "confidence_threshold": settings.ocr_confidence_threshold,
                    "min_text_chars": settings.ocr_min_text_chars,
                    "dpi": settings.ocr_dpi,
                    "log_file": str(log_path),
                },
            )
            try:
                summary = ocr_documents(
                    conn,
                    engine,
                    cache,
                    settings.ocr_confidence_threshold,
                    settings.ocr_min_text_chars,
                )
            except Exception:
                # finished_at stays NULL, marking the run as incomplete.
                log.exception("OCR run %s crashed", run_id)
                print("OCR run crashed; see log file", file=sys.stderr)
                return EXIT_UNEXPECTED
            finish_run(conn, run_id, summary.to_dict())
        finally:
            conn.close()

    print(f"documents checked: {summary.documents_processed}")
    print(f"pages OCR'd:       {summary.pages_ocrd}")
    print(f"documents flagged: {summary.documents_flagged}")
    print(f"pages flagged:     {summary.pages_flagged}")
    print(f"documents failed:  {len(summary.errors)}")
    print(f"log file:          {log_path}")
    for title, message in summary.errors:
        print(f"  failed: {title}: {message}", file=sys.stderr)
    if summary.pages_flagged:
        print("review with: python -m document_store.ingest.review_cli ocr-list")

    return EXIT_FILE_ERRORS if summary.errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())