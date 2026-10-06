"""Tests for benchmark metrics (STORY-3.7)."""

import pytest

from document_store.bench.metrics import character_error_rate, levenshtein, normalise


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("", "", 0),
        ("abc", "abc", 0),
        ("abc", "", 3),
        ("", "abc", 3),
        ("kitten", "sitting", 3),
        ("flaw", "lawn", 2),
    ],
)
def test_levenshtein(a: str, b: str, expected: int) -> None:
    assert levenshtein(a, b) == expected


def test_normalise_collapses_whitespace() -> None:
    assert normalise("  Total \n 12.50\t  ") == "Total 12.50"


def test_perfect_match_scores_zero() -> None:
    assert character_error_rate("Total 12.50", "Total  12.50") == 0.0


def test_one_substitution_in_ten_characters() -> None:
    assert character_error_rate("0123456789", "0123456780") == pytest.approx(0.1)


def test_empty_reference_rules() -> None:
    assert character_error_rate("", "") == 0.0
    assert character_error_rate("", "anything") == 1.0