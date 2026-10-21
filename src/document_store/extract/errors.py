"""Errors shared by text extractors."""


class ExtractionError(Exception):
    """Raised when a file cannot be read by an extractor.

    The message names the file but never includes document text.
    """