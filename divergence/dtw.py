"""Continuous trajectory layer: Dynamic Time Warping.

Spec section 2.3:

    d_traj(tau_i, tau_j) = min_pi [ sum_t || tau_i(t) - tau_j(pi(t)) ||_2 ] / L_pi

where ``L_pi`` is the number of nodes on the optimal warping path. Normalizing by
``L_pi`` (rather than by ``max(|tau_i|, |tau_j|)``) keeps the metric comparable across
trajectories of different lengths, which is the whole point of warping.

A trajectory is a sequence of vectors. 1-D inputs (plain lists of numbers) are accepted
and treated as ``(n, 1)`` matrices, so scalar time series work out of the box.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np

from .errors import DegenerateInput

#: Distance assigned when exactly one trajectory in a pair is degenerate (empty).
#: Symmetric, documented, and keeps D_traj finite so the K-round state machine can
#: still escalate rather than crash.
DEGENERATE_TRAJECTORY_DISTANCE = 1.0


def _as_matrix(trajectory: Any) -> np.ndarray:
    arr = np.asarray(trajectory, dtype=float)
    if arr.size == 0:
        return arr.reshape(0, 0)
    if arr.ndim == 1:
        return arr.reshape(-1, 1)
    if arr.ndim != 2:
        raise DegenerateInput(
            f"trajectory must be 1-D or 2-D, got shape {arr.shape}"
        )
    return arr


def _pairwise_cost(a: np.ndarray, b: np.ndarray, order: float) -> np.ndarray:
    """Local cost matrix ``cost[i, j] = ||a_i - b_j||_order``."""
    diff = a[:, None, :] - b[None, :, :]
    if order == 2.0:
        return np.sqrt(np.sum(diff * diff, axis=2))
    if order == 1.0:
        return np.sum(np.abs(diff), axis=2)
    return np.power(np.sum(np.abs(diff) ** order, axis=2), 1.0 / order)


def dtw_distance(
    a: Any,
    b: Any,
    order: float = 2.0,
    return_path_length: bool = False,
) -> float | tuple[float, int]:
    """Path-length-normalized DTW distance between two trajectories.

    Raises :class:`DegenerateInput` when exactly one trajectory is empty; use
    :func:`trajectory_divergence` when you want the documented penalty instead.
    """
    A = _as_matrix(a)
    B = _as_matrix(b)
    if A.shape[0] == 0 and B.shape[0] == 0:
        return (0.0, 0) if return_path_length else 0.0
    if A.shape[0] == 0 or B.shape[0] == 0:
        raise DegenerateInput("cannot warp an empty trajectory against a non-empty one")
    if A.shape[1] != B.shape[1]:
        raise DegenerateInput(
            f"trajectory dimensionality mismatch: {A.shape[1]} vs {B.shape[1]}"
        )

    n, m = A.shape[0], B.shape[0]
    cost = _pairwise_cost(A, B, order)

    # Accumulated cost DP with 3 moves (diagonal, vertical, horizontal).
    acc = np.full((n, m), np.inf)
    acc[0, 0] = cost[0, 0]
    for i in range(1, n):
        acc[i, 0] = acc[i - 1, 0] + cost[i, 0]
    for j in range(1, m):
        acc[0, j] = acc[0, j - 1] + cost[0, j]
    for i in range(1, n):
        row, prev = acc[i], acc[i - 1]
        crow = cost[i]
        for j in range(1, m):
            row[j] = crow[j] + min(prev[j], row[j - 1], prev[j - 1])

    if not return_path_length:
        return float(acc[n - 1, m - 1]) / _optimal_path_length(acc, cost, n, m)

    length = _optimal_path_length(acc, cost, n, m)
    return float(acc[n - 1, m - 1]) / length, length


def _optimal_path_length(acc: np.ndarray, cost: np.ndarray, n: int, m: int) -> int:
    """Number of nodes on the optimal warping path (backtrack from ``(n-1, m-1)``)."""
    i, j, length = n - 1, m - 1, 1
    while i > 0 or j > 0:
        if i == 0:
            j -= 1
        elif j == 0:
            i -= 1
        else:
            candidates = (
                (acc[i - 1, j - 1], i - 1, j - 1),
                (acc[i - 1, j], i - 1, j),
                (acc[i, j - 1], i, j - 1),
            )
            best = min(candidates, key=lambda c: (c[0], c[1], c[2]))
            i, j = best[1], best[2]
        length += 1
    return length


def pairwise_dtw(
    trajectories: Sequence[Any],
    order: float = 2.0,
    empty_penalty: float = DEGENERATE_TRAJECTORY_DISTANCE,
) -> list[list[float]]:
    """Full symmetric pairwise DTW matrix with a zero diagonal."""
    k = len(trajectories)
    mats = [_as_matrix(t) for t in trajectories]
    out = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i + 1, k):
            ei, ej = mats[i].shape[0] == 0, mats[j].shape[0] == 0
            if ei and ej:
                d = 0.0
            elif ei or ej:
                d = empty_penalty
            else:
                d = float(dtw_distance(mats[i], mats[j], order=order))
            out[i][j] = out[j][i] = d
    return out


def trajectory_divergence(
    trajectories: Iterable[Any],
    order: float = 2.0,
    empty_penalty: float = DEGENERATE_TRAJECTORY_DISTANCE,
) -> float:
    """``D_traj``: mean pairwise path-length-normalized DTW over a cohort.

    Degenerate (empty) trajectories are handled explicitly rather than raising:

    * both empty in a pair -> ``0.0`` (two abstentions agree on nothing happening)
    * exactly one empty    -> ``empty_penalty`` (default ``1.0``)
    """
    return pairwise_mean(pairwise_dtw(list(trajectories), order=order, empty_penalty=empty_penalty))


def pairwise_mean(matrix: Sequence[Sequence[float]]) -> float:
    """Mean of the strict upper triangle of a pairwise distance matrix."""
    k = len(matrix)
    if k < 2:
        return 0.0
    total, pairs = 0.0, 0
    for i in range(k):
        for j in range(i + 1, k):
            total += float(matrix[i][j])
            pairs += 1
    return total / pairs if pairs else 0.0
