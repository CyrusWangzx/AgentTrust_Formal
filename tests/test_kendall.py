"""Concordance layer tests (spec 2.3, Kendall's W)."""

from __future__ import annotations

import pytest

from divergence.kendall import kendalls_w


class TestKendallsW:
    def test_perfect_agreement(self) -> None:
        rankings = [[1, 2, 3, 4], [1, 2, 3, 4], [1, 2, 3, 4]]
        result = kendalls_w(rankings)
        assert result.w == pytest.approx(1.0)
        assert result.reviewers == 3 and result.objects == 4
        assert result.significant is True

    def test_two_reviewers_of_three_objects(self) -> None:
        # m=2, n=3 with reversed orderings: rank sums are [4, 4, 4] = mean rank, so S = 0
        # and therefore W = 0 -- the cohort carries no concordance signal at all.
        result = kendalls_w([[1, 2, 3], [3, 2, 1]])
        assert result.w == pytest.approx(0.0)
        assert result.chi_square == pytest.approx(0.0)

    def test_known_three_by_three_concordance(self) -> None:
        # rank sums [4, 5, 9], mean 6 -> S = 4 + 1 + 9 = 14
        # W = 12*14 / (3^2 * (3^3 - 3)) = 168 / 216 = 0.777...
        result = kendalls_w([[1, 2, 3], [1, 2, 3], [2, 1, 3]])
        assert result.w == pytest.approx(168 / 216)
        assert result.chi_square == pytest.approx(3 * 2 * 168 / 216)

    def test_maximum_disagreement(self) -> None:
        result = kendalls_w([[1, 2, 3], [3, 2, 1]])
        assert 0.0 <= result.w < 1.0

    def test_chi_square_formula(self) -> None:
        rankings = [[1, 2, 3], [2, 3, 1], [3, 1, 2]]
        result = kendalls_w(rankings)
        assert result.chi_square == pytest.approx(3 * (3 - 1) * result.w)
        assert result.degrees_of_freedom == 2
        assert result.w == pytest.approx(0.0)

    def test_ties_are_corrected(self) -> None:
        tied = [[1, 1, 2, 3], [1, 1, 2, 3], [1, 1, 2, 3]]
        result = kendalls_w(tied)
        assert result.tie_correction > 0
        assert result.w == pytest.approx(1.0)

    def test_all_tied_returns_zero_without_crashing(self) -> None:
        result = kendalls_w([[5, 5, 5], [5, 5, 5]])
        assert result.w == 0.0
        assert result.significant is False

    def test_degenerate_cohorts(self) -> None:
        assert kendalls_w([]).w == 0.0
        assert kendalls_w([[1, 2, 3]]).w == 0.0            # single reviewer
        assert kendalls_w([[1], [2]]).w == 0.0             # single object
        assert kendalls_w([[1, 2], [2, 1]]).objects == 2

    def test_ragged_rankings_raise(self) -> None:
        with pytest.raises(ValueError):
            kendalls_w([[1, 2, 3], [1, 2]])

    def test_w_bounded_in_unit_interval(self) -> None:
        for rankings in (
            [[1, 2, 3, 4, 5], [2, 1, 4, 3, 5], [1, 3, 2, 5, 4]],
            [[5, 4, 3, 2, 1], [1, 2, 3, 4, 5]],
        ):
            assert 0.0 <= kendalls_w(rankings).w <= 1.0

    def test_as_dict_round_trip(self) -> None:
        payload = kendalls_w([[1, 2, 3], [1, 2, 3]]).as_dict()
        assert set(payload) == {
            "W", "chi_square", "df", "significant_at_0.05", "reviewers_m",
            "objects_n", "tie_correction",
        }
