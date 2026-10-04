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