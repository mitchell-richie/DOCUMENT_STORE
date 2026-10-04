"""Routing engine: maps doc_class to processing_route."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from document_store.config import RoutingConfig
from document_store.constants import DOC_CLASSES, ENFORCED_ROUTES, PROCESSING_ROUTES
from document_store.ingest.classify import Classifier, relative_to_originals

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Router:
    """Compiled, validated doc_class to processing_route mapping."""

    _mapping: dict[str, str]

    def route_for(self, doc_class: str) -> str:
        """Return the processing_route for a doc_class.

        Raises:
            ValueError: if doc_class has no configured route.
        """
        try:
            return self._mapping[doc_class]
        except KeyError:
            raise ValueError(f"No route configured for doc_class {doc_class!r}") from None


def build_router(config: RoutingConfig) -> Router:
    """Validate the routing configuration and apply enforced overrides.

    Raises:
        ValueError: if any doc_class is missing a route, an unrecognised
            doc_class or processing_route appears, or the mapping is
            otherwise invalid.
    """
    missing = DOC_CLASSES - config.mapping.keys()
    if missing:
        raise ValueError(f"Routing configuration is missing doc_class(es): {sorted(missing)}")

    mapping: dict[str, str] = {}
    for doc_class, route in config.mapping.items():
        if doc_class not in DOC_CLASSES:
            raise ValueError(f"Unrecognised doc_class in routing config: {doc_class!r}")
        if route not in PROCESSING_ROUTES:
            raise ValueError(
                f"Unrecognised processing_route {route!r} for doc_class {doc_class!r}"
            )
        mapping[doc_class] = route

    for doc_class, required_route in ENFORCED_ROUTES.items():
        configured = mapping.get(doc_class)
        if configured != required_route:
            log.warning(
                "overriding configured route %r for doc_class %r: %r is enforced",
                configured,
                doc_class,
                required_route,
            )
            mapping[doc_class] = required_route

    return Router(_mapping=mapping)


def route_document(
    classifier: Classifier,
    router: Router,
    originals_root: Path,
    absolute_path: Path,
) -> tuple[str, str]:
    """Classify a file and return its (doc_class, processing_route)."""
    relative = relative_to_originals(originals_root, absolute_path)
    doc_class = classifier.classify(relative)
    return doc_class, router.route_for(doc_class)