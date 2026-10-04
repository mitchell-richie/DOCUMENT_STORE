"""Tests for document classification (STORY-2.3)."""

from pathlib import Path

import pytest

from document_store.config import ClassificationConfig, ClassificationRule
from document_store.ingest.classify import (
    build_classifier,
    relative_to_originals,
)

RULES = (
    ClassificationRule(doc_class="in_camera", pattern="in_camera/**"),
    ClassificationRule(doc_class="financial_statement", pattern="**/bank_statement*"),
    ClassificationRule(doc_class="receipt", pattern="**/receipt*"),
    ClassificationRule(doc_class="correspondence", pattern="correspondence/**"),
)


@pytest.fixture
def classifier():
    config = ClassificationConfig(rules=RULES, default_doc_class="other")
    return build_classifier(config)


def test_in_camera_folder_is_classified(classifier) -> None:
    assert classifier.classify(Path("in_camera/order.pdf")) == "in_camera"


def test_bank_statement_pattern_matches_nested_path(classifier) -> None:
    path = Path("2024/statements/bank_statement_synthetic_2024-01.pdf")
    assert classifier.classify(path) == "financial_statement"


def test_unmatched_file_receives_default(classifier) -> None:
    assert classifier.classify(Path("misc/unsorted.pdf")) == "other"


def test_matching_is_case_insensitive(classifier) -> None:
    assert classifier.classify(Path("In_Camera/Order.PDF")) == "in_camera"


def test_first_matching_rule_wins() -> None:
    rules = (
        ClassificationRule(doc_class="in_camera", pattern="**/*.pdf"),
        ClassificationRule(doc_class="correspondence", pattern="**/*.pdf"),
    )
    classifier = build_classifier(
        ClassificationConfig(rules=rules, default_doc_class="other")
    )
    assert classifier.classify(Path("anything.pdf")) == "in_camera"


def test_invalid_doc_class_in_rule_raises() -> None:
    rules = (ClassificationRule(doc_class="not_a_class", pattern="**/*.pdf"),)
    with pytest.raises(ValueError, match="Unrecognised doc_class"):
        build_classifier(ClassificationConfig(rules=rules, default_doc_class="other"))


def test_invalid_default_doc_class_raises() -> None:
    with pytest.raises(ValueError, match="Unrecognised doc_class"):
        build_classifier(ClassificationConfig(rules=(), default_doc_class="nope"))


def test_relative_to_originals(tmp_path: Path) -> None:
    root = tmp_path / "originals"
    target = root / "in_camera" / "order.pdf"
    assert relative_to_originals(root, target) == Path("in_camera/order.pdf")


def test_relative_to_originals_outside_root_raises(tmp_path: Path) -> None:
    root = tmp_path / "originals"
    outside = tmp_path / "elsewhere" / "file.pdf"
    with pytest.raises(ValueError):
        relative_to_originals(root, outside)