"""Command-line ingestion: python -m document_store.ingest [path]"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from document_store.config import ConfigError, load_settings
from document_store.db.connection import connect
from document_store.db.migrate import migrate
from document_store.ingest.classify import build_classifier
from document_store.ingest.pipeline import check_within_originals, ingest_folder
from document_store.ingest.routing import build_router

EXIT_OK = 0
EXIT_FILE_ERRORS = 1
EXIT_CONFIG_ERROR = 2


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

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

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

    conn = connect(settings.paths.database)
    try:
        migrate(conn)
        summary = ingest_folder(conn, classifier, router, originals, root)
    finally:
        conn.close()

    print(f"documents created:  {summary.documents_created}")
    print(f"documents existing: {summary.documents_existing}")
    print(f"routes upgraded:    {summary.routes_upgraded}")
    print(f"files skipped:      {len(summary.skipped)}")
    print(f"files failed:       {len(summary.errors)}")
    for path, message in summary.errors:
        print(f"  failed: {path.name}: {message}", file=sys.stderr)

    return EXIT_FILE_ERRORS if summary.errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())