"""Continuous trajectory layer tests (spec 2.3, ``D_traj``)."""

from __future__ import annotations

import pytest

from divergence.dtw import (
    DEGENERATE_TRAJECTORY_DISTANCE,
    dtw_distance,
    pairwise_dtw,
    pairwise_mean,
    trajectory_divergence,
)
from divergence.errors import DegenerateInput


class TestDtwDistance:
    def test_identical_trajectories_are_zero(self) -> None:
        traj = [[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]
        assert dtw_distance(traj, traj) == pytest.approx(0.0)

    def test_scalar_series_supported(self) -> None:
        assert dtw_distance([0.0, 1.0, 2.0], [0.0, 1.0, 2.0]) == pytest.approx(0.0)

    def test_shifted_series_warps_instead_of_overpaying(self) -> None:
        # A constant +1 offset. Naive 1:1 alignment costs 1.0 per step, but DTW may skip
        # a node: the optimal path is (0,0),(1,0),(2,1),(2,2) -> cost 2 over 4 nodes = 0.5.
        a = [[0.0], [1.0], [2.0]]
        b = [[1.0], [2.0], [3.0]]
        d = dtw_distance(a, b)
        assert d == pytest.approx(0.5)
        naive = sum(abs(x[0] - y[0]) for x, y in zip(a, b)) / len(a)
        assert d < naive

    def test_time_warping_beats_naive_alignment(self) -> None:
        a = [[0.0], [1.0], [2.0], [3.0]]
        b = [[0.0], [2.0], [3.0]]
        warped = dtw_distance(a, b)
        naive = sum(abs(x[0] - y[0]) for x, y in zip(a, b[:3])) / 3
        assert warped <= naive

    def test_symmetric(self) -> None:
        a = [[0.0, 0.0], [1.0, 0.5], [2.0, 1.0]]
        b = [[0.0, 0.1], [0.9, 0.4], [2.1, 1.2], [2.5, 1.5]]
        assert dtw_distance(a, b) == pytest.approx(dtw_distance(b, a))

    def test_path_length_returned(self) -> None:
        d, length = dtw_distance([[0.0], [1.0]], [[0.0], [1.0]], return_path_length=True)
        assert d == pytest.approx(0.0)
        assert length == 2

    def test_both_empty_is_zero(self) -> None:
        assert dtw_distance([], []) == pytest.approx(0.0)

    def test_one_empty_raises(self) -> None:
        with pytest.raises(DegenerateInput):
            dtw_distance([], [[0.0], [1.0]])
        with pytest.raises(DegenerateInput):
            dtw_distance([[0.0]], [])

    def test_dimension_mismatch_raises(self) -> None:
        with pytest.raises(DegenerateInput):
            dtw_distance([[0.0, 0.0]], [[0.0]])

    def test_single_step_actions(self) -> None:
        # one action each: DTW degenerates to plain L2 with path length 1
        d = dtw_distance([[3.0, 4.0]], [[0.0, 0.0]])
        assert d == pytest.approx(5.0)


class TestPairwiseDtw:
    def test_matrix_is_symmetric_with_zero_diagonal(self) -> None:
        trajs = [[[0.0], [1.0]], [[0.0], [2.0]], [[0.0], [1.5]]]
        matrix = pairwise_dtw(trajs)
        for i in range(3):
            assert matrix[i][i] == 0.0
            for j in range(3):
                assert matrix[i][j] == pytest.approx(matrix[j][i])

    def test_degenerate_pair_penalty(self) -> None:
        matrix = pairwise_dtw([[[0.0], [1.0]], []])
        assert matrix[0][1] == DEGENERATE_TRAJECTORY_DISTANCE

    def test_two_degenerate_trajectories_agree(self) -> None:
        matrix = pairwise_dtw([[], []])
        assert matrix[0][1] == 0.0


class TestTrajectoryDivergence:
    def test_all_identical_is_zero(self) -> None:
        traj = [[0.0, 0.0], [1.0, 1.0]]
        assert trajectory_divergence([traj] * 4) == pytest.approx(0.0)

    def test_single_cohort_member_is_zero(self) -> None:
        assert trajectory_divergence([[[0.0]]]) == 0.0
        assert trajectory_divergence([]) == 0.0

    def test_empty_trajectory_does_not_crash(self) -> None:
        value = trajectory_divergence([[], [[0.0], [1.0]]])
        assert value == pytest.approx(DEGENERATE_TRAJECTORY_DISTANCE)

    def test_all_empty_is_zero(self) -> None:
        assert trajectory_divergence([[], [], []]) == 0.0

    @pytest.mark.parametrize("count", [2, 3, 4, 5])
    def test_odd_and_even_cohorts(self, count: int) -> None:
        base = [[[0.0], [0.0]]] * (count - 1) + [[[5.0], [5.0]]]
        assert trajectory_divergence(base) > 0.0

    def test_pairwise_mean_helper(self) -> None:
        assert pairwise_mean([[0.0, 2.0], [2.0, 0.0]]) == 2.0
        assert pairwise_mean([[0.0]]) == 0.0
        assert pairwise_mean([]) == 0.0
