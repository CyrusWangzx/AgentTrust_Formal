"""Terminal state layer tests (spec 2.3, ``D_end``)."""

from __future__ import annotations

import numpy as np
import pytest

from divergence.distance import (
    DEGENERATE_STATE_DISTANCE,
    l2_distance,
    mahalanobis_distance,
    pooled_covariance,
    terminal_divergence,
)
from divergence.errors import DegenerateInput


class TestL2Distance:
    def test_zero_for_identical(self) -> None:
        assert l2_distance([1.0, 2.0], [1.0, 2.0]) == 0.0

    def test_pythagorean_triple(self) -> None:
        assert l2_distance([3.0, 4.0], [0.0, 0.0]) == pytest.approx(5.0)

    def test_dimension_mismatch_raises(self) -> None:
        with pytest.raises(DegenerateInput):
            l2_distance([1.0, 2.0], [1.0])


class TestMahalanobis:
    def test_identity_covariance_matches_l2(self) -> None:
        cov = np.eye(2)
        assert mahalanobis_distance([1.0, 1.0], [0.0, 0.0], cov) == pytest.approx(
            l2_distance([1.0, 1.0], [0.0, 0.0])
        )

    def test_scale_covariance_downweights_noisy_axis(self) -> None:
        cov = np.diag([4.0, 0.25])
        d = mahalanobis_distance([2.0, 0.5], [0.0, 0.0], cov)
        assert d == pytest.approx(np.sqrt(2.0), rel=1e-6)

    def test_singular_covariance_falls_back_to_pinv(self) -> None:
        singular = np.array([[1.0, 1.0], [1.0, 1.0]])
        d = mahalanobis_distance([1.0, 0.0], [0.0, 0.0], singular)
        assert d >= 0.0

    def test_covariance_shape_mismatch_raises(self) -> None:
        with pytest.raises(DegenerateInput):
            mahalanobis_distance([1.0, 2.0], [0.0, 0.0], np.eye(3))


class TestTerminalDivergence:
    def test_all_identical_is_zero(self) -> None:
        assert terminal_divergence([[1.0, 2.0]] * 4) == pytest.approx(0.0)

    def test_single_member_is_zero(self) -> None:
        assert terminal_divergence([[1.0]]) == 0.0
        assert terminal_divergence([]) == 0.0

    def test_two_members(self) -> None:
        assert terminal_divergence([[0.0, 0.0], [0.0, 3.0]]) == pytest.approx(3.0)

    def test_missing_state_is_penalised(self) -> None:
        assert terminal_divergence([[1.0], None]) == pytest.approx(DEGENERATE_STATE_DISTANCE)

    def test_two_missing_states_agree(self) -> None:
        assert terminal_divergence([None, None]) == 0.0

    def test_mahalanobis_metric_runs(self) -> None:
        states = [[0.0, 0.0], [1.0, 2.0], [2.0, 1.0], [0.5, 0.5]]
        assert terminal_divergence(states, metric="mahalanobis") >= 0.0

    def test_unknown_metric_raises(self) -> None:
        with pytest.raises(ValueError):
            terminal_divergence([[1.0], [2.0]], metric="cosine")

    @pytest.mark.parametrize("count", [2, 3, 4, 5])
    def test_odd_and_even_cohorts(self, count: int) -> None:
        states = [[0.0]] * (count - 1) + [[2.0]]
        expected = 2.0 * (count - 1) / (count * (count - 1) / 2)
        assert terminal_divergence(states) == pytest.approx(expected)


class TestPooledCovariance:
    def test_shape_and_regularization(self) -> None:
        cov = pooled_covariance([[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]])
        assert cov.shape == (2, 2)
        assert np.all(np.isfinite(cov))

    def test_single_sample_is_invertible(self) -> None:
        cov = pooled_covariance([[1.0, 2.0]])
        assert np.linalg.matrix_rank(cov) == 2
