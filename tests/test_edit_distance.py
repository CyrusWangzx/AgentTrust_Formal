"""Discrete action layer tests (spec 2.3, ``D_disc``)."""

from __future__ import annotations

import pytest

from divergence.edit_distance import (
    DEGENERATE_SEQUENCE_DISTANCE,
    edit_distance_norm,
    levenshtein,
    sequence_divergence,
)


class TestLevenshtein:
    def test_identical(self) -> None:
        assert levenshtein(["a", "b", "c"], ["a", "b", "c"]) == 0

    def test_substitution(self) -> None:
        assert levenshtein(["a", "b", "c"], ["a", "x", "c"]) == 1

    def test_insert_delete(self) -> None:
        assert levenshtein(["a", "b"], ["a", "b", "c"]) == 1
        assert levenshtein(["a", "b", "c"], ["a", "c"]) == 1

    def test_empty_cases(self) -> None:
        assert levenshtein([], []) == 0
        assert levenshtein([], ["a", "b"]) == 2
        assert levenshtein(["a"], []) == 1

    def test_classic_kitten(self) -> None:
        assert levenshtein(list("kitten"), list("sitting")) == 3

    def test_symmetry(self) -> None:
        a, b = ["move", "grip", "lift"], ["move", "lift", "place", "release"]
        assert levenshtein(a, b) == levenshtein(b, a)


class TestNormalizedEditDistance:
    def test_identical_is_zero(self) -> None:
        assert edit_distance_norm(["a", "b"], ["a", "b"]) == 0.0

    def test_fully_disjoint_is_one(self) -> None:
        assert edit_distance_norm(["a", "b"], ["x", "y"]) == 1.0

    def test_denominator_is_max_length(self) -> None:
        # 1 edit over max(3, 4) = 4
        assert edit_distance_norm(["a", "b", "c"], ["a", "b", "c", "d"]) == pytest.approx(0.25)

    def test_both_empty_is_zero(self) -> None:
        assert edit_distance_norm([], []) == 0.0

    def test_one_empty_is_degenerate_penalty(self) -> None:
        assert edit_distance_norm([], ["a"]) == DEGENERATE_SEQUENCE_DISTANCE
        assert edit_distance_norm(["a"], []) == DEGENERATE_SEQUENCE_DISTANCE

    def test_range_is_bounded(self) -> None:
        for a, b in (
            (["a"], ["b", "c", "d"]),
            (["a", "b", "c", "d"], ["a"]),
            (["x"], ["x"]),
        ):
            assert 0.0 <= edit_distance_norm(a, b) <= 1.0

    def test_normalize_hook(self) -> None:
        assert edit_distance_norm(["MOVE(A)"], ["move(a)"], normalize=str.lower) == 0.0

    def test_symmetric(self) -> None:
        a, b = ["p", "q", "r"], ["p", "r", "s", "t"]
        assert edit_distance_norm(a, b) == edit_distance_norm(b, a)


class TestSequenceDivergence:
    def test_single_validator_is_zero(self) -> None:
        assert sequence_divergence([["a", "b"]]) == 0.0
        assert sequence_divergence([]) == 0.0

    def test_all_identical_is_zero(self) -> None:
        assert sequence_divergence([["a", "b", "c"]] * 5) == 0.0

    def test_complete_disagreement_is_one(self) -> None:
        assert sequence_divergence([["a", "b"], ["x", "y"]]) == 1.0

    def test_pairwise_mean_formula(self) -> None:
        # Lev(s1, s2) = 1 over max(|s1|, |s2|) = 4  ->  d = 0.25
        # pairs: d(1,2)=0, d(1,3)=0.25, d(2,3)=0.25  ->  mean = 0.5 / 3
        s1 = ["a", "b", "c", "d"]
        s2 = ["a", "b", "c", "x"]
        seq = sequence_divergence([s1, s1, s2])
        assert seq == pytest.approx(0.5 / 3)

    @pytest.mark.parametrize("count", [2, 3, 4, 5, 6, 7])
    def test_odd_and_even_cohorts(self, count: int) -> None:
        sequences = [["a", "b"]] * (count - 1) + [["x", "y"]]
        expected = (count - 1) / (count * (count - 1) / 2)  # outlier pairs / total pairs
        assert sequence_divergence(sequences) == pytest.approx(expected)
