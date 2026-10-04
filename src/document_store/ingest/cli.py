"""Command-line ingestion: python -m document_store.ingest [path]"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from document_store.config import ConfigError, load_settings
from document_store.db.connection import connect
from document_store.db.migrate import migrate
from document_store.ingest.classify import build_classifier
from document_store.ingest.pipeline import check_within_originals, ingest_folder
from document_store.ingest.routing import build_router
from document_store.ingest.runlog import finish_run, start_run
from document_store.logs import configure_console, run_log_file

EXIT_OK = 0
EXIT_FILE_ERRORS = 1
EXIT_CONFIG_ERROR = 2
EXIT_UNEXPECTED = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest case documents.")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=None,
        help="folder to ingest (default: the originals folder); must be inside it",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/config.toml"),
        help="configuration file (default: config/config.toml)",
    )
    args = parser.parse_args(argv)

    configure_console()
    log = logging.getLogger(__name__)

    try:
        settings = load_settings(args.config)
        classifier = build_classifier(settings.classification)
        router = build_router(settings.routing)
    except (ConfigError, ValueError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    originals = settings.paths.originals.resolve()
    root = (args.path or originals).resolve()
    try:
        check_within_originals(originals, root)
    except ValueError:
        print(f"path must be inside the originals folder: {originals}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with run_log_file(settings.paths.logs, "ingest", stamp) as log_path:
        conn = connect(settings.paths.database)
        try:
            migrate(conn)
            run_id = start_run(
                conn,
                stage="ingest",
                parameters={"root": str(root), "log_file": str(log_path)},
            )
            try:
                summary = ingest_folder(conn, classifier, router, originals, root)
            except Exception:
                # finished_at stays NULL, marking the run as incomplete.
                log.exception("ingestion run %s crashed", run_id)
                print("ingestion crashed; see log file", file=sys.stderr)
                return EXIT_UNEXPECTED
            finish_run(conn, run_id, summary.to_dict())
        finally:
            conn.close()

    print(f"documents created:  {summary.documents_created}")
    print(f"documents existing: {summary.documents_existing}")
    print(f"routes upgraded:    {summary.routes_upgraded}")
    print(f"files skipped:      {len(summary.skipped)}")
    print(f"files failed:       {len(summary.errors)}")
    print(f"log file:           {log_path}")
    for path, message in summary.errors:
        print(f"  failed: {path.name}: {message}", file=sys.stderr)

    return EXIT_FILE_ERRORS if summary.errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())