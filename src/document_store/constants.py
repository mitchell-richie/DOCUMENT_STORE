"""Enumerations shared across modules, matching CHECK constraints in the schema."""

DOC_CLASSES = frozenset(
    {
        "correspondence",
        "court_filing",
        "in_camera",
        "financial_statement",
        "receipt",
        "other",
        "unclassified",
    }
)

# Route restrictiveness, most restrictive first. This is the single source of
# truth for valid routes: PROCESSING_ROUTES is derived from it. Adding a route
# requires adding it here (and a schema migration for the CHECK constraints).
ROUTE_RESTRICTIVENESS: dict[str, int] = {
    "local_only": 3,
    "index_only": 2,
    "external": 1,
    "standard": 0,
}

PROCESSING_ROUTES = frozenset(ROUTE_RESTRICTIVENESS)

# Routes that cannot be overridden by configuration, regardless of the
# value supplied. A mismatch is logged as a warning and then corrected.
ENFORCED_ROUTES = {
    "in_camera": "local_only",
}

# Routes whose documents have their content processed (OCR now; chunking and
# embedding from EPIC-4). index_only and external documents are registered,
# but their content is never read by this system.
CONTENT_ROUTES = frozenset({"local_only", "standard"})

# External systems that hold the content of documents on the `external`
# route, keyed by doc_class. Every doc_class routed `external` must appear
# here; the router checks this at startup. The external_record for such a
# document uses this name as external_system and the source file's SHA-256
# as external_id, so the other tool can find the same file by content.
EXTERNAL_SYSTEMS: dict[str, str] = {
    "financial_statement": "bank_statement_tool",
}
