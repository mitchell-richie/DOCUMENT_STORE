"""Allow: python -m document_store.ingest"""

import sys

from document_store.ingest.cli import main

sys.exit(main())