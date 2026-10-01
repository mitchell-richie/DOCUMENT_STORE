"""Enumerations shared across modules, matching CHECK constraints in the schema."""

DOC_CLASSES = frozenset(
    {
        "correspondence",
        "court_filing",
        "in_camera",
        "financial_statement",
        "receipt",
        "other",
    }
)

PROCESSING_ROUTES = frozenset({"standard", "local_only", "index_only", "external"})