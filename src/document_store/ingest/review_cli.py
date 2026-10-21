"""Command-line review: python -m document_store.ingest.review_cli <command>"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from document_store.config import ConfigError, load_settings
from document_store.db.connection import connect
from document_store.db.migrate import migrate
from document_store.ingest.documents import DOWNGRADE_WARNING, RiskAcknowledgementRequired
from document_store.ingest.ocr_flags import list_flagged, mark_reviewed
from document_store.ingest.review import list_unclassified, reclassify
from document_store.ingest.routing import Router, build_router

EXIT_OK = 0
EXIT_RISK_NOT_ACKNOWLEDGED = 1
EXIT_ERROR = 2


def _list_unclassified(conn: sqlite3.Connection) -> int:
    documents = list_unclassified(conn)
    if not documents:
        print("No unclassified documents.")
    for doc in documents:
        print(f"{doc.document_id}\t{doc.processing_route}\t{doc.title}")
    return EXIT_OK


def _reclassify(conn: sqlite3.Connection, router: Router, args: argparse.Namespace) -> int:
    try:
        changed = reclassify(
            conn,
            router,
            args.document_id,
            args.doc_class,
            args.reason,
            risk_acknowledged=args.acknowledge_risk,
        )
    except RiskAcknowledgementRequired:
        print(DOWNGRADE_WARNING, file=sys.stderr)
        print("Re-run with --acknowledge-risk to proceed.", file=sys.stderr)
        return EXIT_RISK_NOT_ACKNOWLEDGED
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print("reclassified" if changed else "no change")
    return EXIT_OK


def _list_ocr(conn: sqlite3.Connection) -> int:
    pages = list_flagged(conn)
    if not pages:
        print("No low-confidence pages awaiting review.")
    for page in pages:
        print(
            f"{page.document_id}\t{page.page_number}\t{page.mean_confidence:.2f}"
            f"\t{page.engine}\t{page.title}"
        )
    return EXIT_OK


def _mark_ocr_reviewed(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    try:
        cleared = mark_reviewed(conn, args.document_id, page_number=args.page, note=args.note)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"cleared {cleared} page(s)" if cleared else "nothing to clear")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review documents.")
    parser.add_argument("--config", type=Path, default=Path("config/config.toml"))
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="list unclassified documents")

    reclass = commands.add_parser("reclassify", help="set a document's class")
    reclass.add_argument("document_id", type=int)
    reclass.add_argument("doc_class")
    reclass.add_argument("--reason", required=True)
    reclass.add_argument(
        "--acknowledge-risk",
        action="store_true",
        help="required to make a document less restrictive",
    )

    commands.add_parser("ocr-list", help="list low-confidence OCR pages awaiting review")

    reviewed = commands.add_parser(
        "ocr-reviewed", help="mark a document's low-confidence pages as reviewed"
    )
    reviewed.add_argument("document_id", type=int)
    reviewed.add_argument(
        "--page", type=int, help="page number; omit to clear every flagged page"
    )
    reviewed.add_argument("--note", help="optional note on what was checked")

    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.config)
        router = build_router(settings.routing)
    except (ConfigError, ValueError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    conn = connect(settings.paths.database)
    try:
        migrate(conn)
        if args.command == "list":
            return _list_unclassified(conn)
        if args.command == "reclassify":
            return _reclassify(conn, router, args)
        if args.command == "ocr-list":
            return _list_ocr(conn)
        return _mark_ocr_reviewed(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())