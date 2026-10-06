"""Text comparison metrics for OCR benchmarking."""

from __future__ import annotations


def normalise(text: str) -> str:
    """Collapse runs of whitespace to single spaces and strip the ends."""
    return " ".join(text.split())


def levenshtein(a: str, b: str) -> int:
    """Edit distance between two strings (insertions, deletions, substitutions)."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein distance divided by the reference length, after normalisation.

    An empty reference scores 0.0 if the hypothesis is also empty, otherwise 1.0.
    """
    ref = normalise(reference)
    hyp = normalise(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)