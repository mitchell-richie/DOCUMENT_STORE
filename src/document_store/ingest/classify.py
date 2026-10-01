"""Document classification: assign doc_class from configured path patterns."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pathspec

from document_store.config import ClassificationConfig, ClassificationRule
from document_store.constants import DOC_CLASSES


@dataclass(frozen=True)
class Classifier:
    """Compiled classification rules, evaluated in order."""

    _compiled: tuple[tuple[str, pathspec.PathSpec], ...]
    default_doc_class: str

    def classify(self, relative_path: Path) -> str:
        """Return the doc_class for a path relative to the originals root."""
        posix = relative_path.as_posix().lower()
        for doc_class, spec in self._compiled:
            if spec.match_file(posix):
                return doc_class
        return self.default_doc_class


def build_classifier(config: ClassificationConfig) -> Classifier:
    """Compile configured rules into a Classifier.

    Raises:
        ValueError: if any configured doc_class is not a recognised value.
    """
    _validate_doc_class(config.default_doc_class)
    compiled = tuple(
        (rule.doc_class, _compile_rule(rule)) for rule in config.rules
    )
    return Classifier(_compiled=compiled, default_doc_class=config.default_doc_class)


def _compile_rule(rule: ClassificationRule) -> pathspec.PathSpec:
    _validate_doc_class(rule.doc_class)
    return pathspec.PathSpec.from_lines("gitignore", [rule.pattern.lower()])


def _validate_doc_class(doc_class: str) -> None:
    if doc_class not in DOC_CLASSES:
        raise ValueError(
            f"Unrecognised doc_class {doc_class!r}; expected one of {sorted(DOC_CLASSES)}"
        )


def relative_to_originals(originals_root: Path, absolute_path: Path) -> Path:
    """Return a path relative to the originals root, for use with Classifier.classify.

    Raises:
        ValueError: if absolute_path is not beneath originals_root.
    """
    return absolute_path.resolve().relative_to(originals_root.resolve())