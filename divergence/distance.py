"""Terminal state layer: L2 and Mahalanobis distance.

Spec section 2.3:

    d_end(i, j) = ||x_end,i - x_end,j||_2      (pairwise mean -> D_end)

Spec section 3.2.2: when the terminal state vector mixes dimensions with different
units (e.g. metres and radians), the plain L2 distance is scale-dominated and the
Mahalanobis distance should be used instead:

    d_mahalanobis(x, y) = sqrt( (x - y)^T Sigma^-1 (x - y) )

``Sigma`` is the pooled covariance of the cohort's terminal states. Two guards matter in
practice and both are explicit here: the pooled covariance needs ``N > d`` samples to be
invertible, and samples that are re-used across columns make it singular. We therefore
use the pseudo-inverse with a documented ridge fallback rather than crashing.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np

from .dtw import pairwise_mean
from .errors import DegenerateInput

#: Distance assigned when exactly one terminal state is missing while the other exists.
DEGENERATE_STATE_DISTANCE = 1.0

#: Ridge added to the pooled covariance diagonal when it is rank-deficient.
DEFAULT_RIDGE = 1e-6


def _as_vectors(states: Sequence[Any]) -> tuple[np.ndarray, list[bool]]:
    """Return ``(matrix, present_mask)`` where absent states become zero rows."""
    dims = {np.asarray(s, dtype=float).size for s in states if s is not None}
    if not dims:
        return np.zeros((len(states), 0)), [s is not None for s in states]
    dim = max(dims)
    present = []
    rows = []
    for s in states:
        if s is None:
            present.append(False)
            rows.append(np.zeros(dim))
            continue
        vec = np.asarray(s, dtype=float).reshape(-1)
        if vec.size != dim:
            raise DegenerateInput(
                f"terminal state vectors must share a dimension; got {vec.size} vs {dim}"
            )
        present.append(True)
        rows.append(vec)
    return np.vstack(rows), present


def l2_distance(a: Any, b: Any) -> float:
    """Euclidean distance between two terminal state vectors."""
    va = np.asarray(a, dtype=float).reshape(-1)
    vb = np.asarray(b, dtype=float).reshape(-1)
    if va.size != vb.size:
        raise DegenerateInput(
            f"terminal state vectors must share a dimension; got {va.size} vs {vb.size}"
        )
    return float(np.linalg.norm(va - vb))


def mahalanobis_distance(
    a: Any,
    b: Any,
    covariance: Any,
    ridge: float = DEFAULT_RIDGE,
) -> float:
    """Mahalanobis distance with a pseudo-inverse / ridge fallback."""
    va = np.asarray(a, dtype=float).reshape(-1)
    vb = np.asarray(b, dtype=float).reshape(-1)
    if va.size != vb.size:
        raise DegenerateInput(
            f"terminal state vectors must share a dimension; got {va.size} vs {vb.size}"
        )
    cov = np.atleast_2d(np.asarray(covariance, dtype=float))
    if cov.shape != (va.size, va.size):
        raise DegenerateInput(
            f"covariance must be {va.size}x{va.size}, got {cov.shape}"
        )
    try:
        inv = np.linalg.inv(cov)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(cov + ridge * np.eye(va.size))
    delta = va - vb
    return float(np.sqrt(max(delta @ inv @ delta, 0.0)))


def pooled_covariance(states: Sequence[Any], ridge: float = DEFAULT_RIDGE) -> np.ndarray:
    """Pooled covariance of the present terminal states, regularized to be invertible."""
    matrix, present = _as_vectors(states)
    usable = matrix[np.array(present, dtype=bool)] if any(present) else matrix[:0]
    if usable.shape[0] == 0:
        return np.zeros((matrix.shape[1], matrix.shape[1]))
    if usable.shape[0] == 1:
        return np.eye(usable.shape[1]) * ridge
    cov = np.cov(usable, rowvar=False, bias=True)
    cov = np.atleast_2d(np.asarray(cov, dtype=float))
    return cov + ridge * np.eye(cov.shape[0])


def terminal_divergence(
    states: Iterable[Any],
    metric: str = "l2",
    ridge: float = DEFAULT_RIDGE,
    empty_penalty: float = DEGENERATE_STATE_DISTANCE,
) -> float:
    """``D_end``: mean pairwise terminal-state distance over a cohort.

    ``metric`` is ``"l2"`` (default) or ``"mahalanobis"``. Missing terminal states
    (``None``) are treated as degenerate: two missing states agree (``0.0``), one missing
    yields ``empty_penalty``.
    """
    state_list = list(states)
    matrix, present = _as_vectors(state_list)
    k = len(state_list)
    if k < 2:
        return 0.0
    if metric not in ("l2", "mahalanobis"):
        raise ValueError(f"unknown terminal metric {metric!r}; expected 'l2' or 'mahalanobis'")
    cov = pooled_covariance(state_list, ridge=ridge) if metric == "mahalanobis" else None

    values = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i + 1, k):
            if not present[i] and not present[j]:
                d = 0.0
            elif not present[i] or not present[j]:
                d = empty_penalty
            elif metric == "mahalanobis":
                d = mahalanobis_distance(matrix[i], matrix[j], cov, ridge=ridge)
            else:
                d = l2_distance(matrix[i], matrix[j])
            values[i][j] = values[j][i] = d
    return pairwise_mean(values)
