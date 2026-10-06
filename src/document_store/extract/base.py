"""Base class for format-specific text extractors.

An extractor runs one fixed sequence: open the source, check it, read it,
and close it. Subclasses supply the format-specific steps. Failures to open a
source are mapped to ExtractionError, so every format reports unreadable
files the same way.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from document_store.extract.errors import ExtractionError

DEFAULT_MIN_TEXT_CHARS = 20


class Extractor[ResultT](ABC):
    format_name: ClassVar[str]
    open_errors: ClassVar[tuple[type[BaseException], ...]]

    def __init__(self, path: Path) -> None:
        self.path = path

    def extract(self) -> ResultT:
        """Open, check, and read the source, then close it.

        Raises:
            ExtractionError: if the source cannot be opened or is unusable.
        """
        try:
            source = self._open()
        except self.open_errors as exc:
            raise ExtractionError(
                f"cannot open {self.format_name}: {self.path.name}"
            ) from exc
        try:
            self._check(source)
            return self._read(source)
        finally:
            self._close(source)

    @abstractmethod
    def _open(self) -> Any:
        """Open the source. Library errors listed in open_errors are mapped."""

    def _check(self, source: Any) -> None:
        """Raise ExtractionError for a source that is open but unusable."""

    @abstractmethod
    def _read(self, source: Any) -> ResultT:
        """Produce the extraction result from an open source."""

    def _close(self, source: Any) -> None:
        """Release the source. Called even if reading fails."""