"""Tests for the routing engine (STORY-2.4)."""

import logging
from pathlib import Path

import pytest

from document_store.config import ClassificationConfig, ClassificationRule, RoutingConfig
from document_store.constants import DOC_CLASSES
from document_store.ingest.classify import build_classifier
from document_store.ingest.routing import Router, build_router, route_document

FULL_MAPPING = {
    "in_camera": "local_only",
    "financial_statement": "external",
    "receipt": "standard",
    "court_filing": "standard",
    "correspondence": "standard",
    "other": "local_only",
}


def test_full_mapping_builds_without_error() -> None:
    router = build_router(RoutingConfig(mapping=FULL_MAPPING))
    for doc_class, expected_route in FULL_MAPPING.items():
        assert router.route_for(doc_class) == expected_route


@pytest.mark.parametrize("doc_class", sorted(DOC_CLASSES))
def test_every_doc_class_has_a_route(doc_class: str) -> None:
    router = build_router(RoutingConfig(mapping=FULL_MAPPING))
    assert router.route_for(doc_class) in {"standard", "local_only", "index_only", "external"}


def test_missing_doc_class_raises() -> None:
    incomplete = dict(FULL_MAPPING)
    del incomplete["receipt"]
    with pytest.raises(ValueError, match="missing doc_class"):
        build_router(RoutingConfig(mapping=incomplete))


def test_unrecognised_doc_class_key_raises() -> None:
    invalid = dict(FULL_MAPPING)
    invalid["not_a_class"] = "standard"
    with pytest.raises(ValueError, match="Unrecognised doc_class"):
        build_router(RoutingConfig(mapping=invalid))


def test_unrecognised_route_value_raises() -> None:
    invalid = dict(FULL_MAPPING)
    invalid["receipt"] = "not_a_route"
    with pytest.raises(ValueError, match="Unrecognised processing_route"):
        build_router(RoutingConfig(mapping=invalid))


def test_in_camera_is_forced_to_local_only_even_if_misconfigured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    misconfigured = dict(FULL_MAPPING)
    misconfigured["in_camera"] = "standard"

    with caplog.at_level(logging.WARNING):
        router = build_router(RoutingConfig(mapping=misconfigured))

    assert router.route_for("in_camera") == "local_only"
    assert "overriding configured route" in caplog.text


def test_route_for_unmapped_class_raises() -> None:
    router = Router(_mapping={"other": "local_only"})
    with pytest.raises(ValueError, match="No route configured"):
        router.route_for("receipt")


def test_route_document_combines_classification_and_routing(tmp_path: Path) -> None:
    originals = tmp_path / "originals"
    (originals / "in_camera").mkdir(parents=True)
    target = originals / "in_camera" / "order.pdf"
    target.touch()

    classifier = build_classifier(
        ClassificationConfig(
            rules=(ClassificationRule(doc_class="in_camera", pattern="in_camera/**"),),
            default_doc_class="other",
        )
    )
    router = build_router(RoutingConfig(mapping=FULL_MAPPING))

    doc_class, route = route_document(classifier, router, originals, target)

    assert doc_class == "in_camera"
    assert route == "local_only"


def test_route_document_defaults_unmatched_file_to_local_only(tmp_path: Path) -> None:
    originals = tmp_path / "originals"
    originals.mkdir()
    target = originals / "unsorted.pdf"
    target.touch()

    classifier = build_classifier(
        ClassificationConfig(rules=(), default_doc_class="other")
    )
    router = build_router(RoutingConfig(mapping=FULL_MAPPING))

    doc_class, route = route_document(classifier, router, originals, target)

    assert doc_class == "other"
    assert route == "local_only"