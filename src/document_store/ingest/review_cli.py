"""Command-line review: python -m document_store.ingest.review_cli <command>"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from document_store.config import ConfigError, load_settings
from document_store.db.connection import connect
from document_store.db.migrate import migrate
from document_store.ingest.documents import DOWNGRADE_WARNING, RiskAcknowledgementRequired
from document_store.ingest.review import list_unclassified, reclassify
from document_store.ingest.routing import build_router

EXIT_OK = 0
EXIT_RISK_NOT_ACKNOWLEDGED = 1
EXIT_ERROR = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review document classification.")
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
            documents = list_unclassified(conn)
            if not documents:
                print("No unclassified documents.")
            for doc in documents:
                print(f"{doc.document_id}\t{doc.processing_route}\t{doc.title}")
            return EXIT_OK

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
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())