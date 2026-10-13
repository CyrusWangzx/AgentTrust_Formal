"""Concordance layer: Kendall's W coefficient of concordance.

Spec section 2.3 / 3.2.2:

    W = 12 S / [ m^2 (n^3 - n) ]        S = sum_j ( R_j - m(n+1)/2 )^2
    chi^2 = m (n - 1) W                 df = n - 1

``m`` reviewers, ``n`` ranked objects, ``R_j`` the rank sum of object ``j``. W -> 1 means
the reviewers order the objects the same way; W -> 0 means their orderings are unrelated.

Ties are handled with midranks and the standard tie correction:

    W = 12 S / [ m^2 (n^3 - n) - m * sum_k (t_k^3 - t_k) ]

This is a *statistical cross-check* on the cohort, not part of ``D_total``. The spec uses
it to decide whether a high-divergence round is a genuine consensus-of-dissent (escalate)
or just noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

#: chi-square critical values (alpha = 0.05) keyed by degrees of freedom.
#: Used as a small dependency-free significance gate. df > 30 falls back to the
#: normal approximation with the Wilson-Hilferty transform.
_CHI2_005: dict[int, float] = {
    1: 3.841, 2: 5.991, 3: 7.815, 4: 9.488, 5: 11.070, 6: 12.592, 7: 14.067,
    8: 15.507, 9: 16.919, 10: 18.307, 11: 19.675, 12: 21.026, 13: 22.362,
    14: 23.685, 15: 24.996, 16: 26.296, 17: 27.587, 18: 28.869, 19: 30.144,
    20: 31.410, 21: 32.671, 22: 33.924, 23: 35.172, 24: 36.415, 25: 37.652,
    26: 38.885, 27: 40.113, 28: 41.337, 29: 42.557, 30: 43.773,
}


@dataclass(frozen=True)
class KendallResult:
    """Result of a Kendall's W computation."""

    w: float
    chi_square: float
    degrees_of_freedom: int
    significant: bool
    reviewers: int
    objects: int
    tie_correction: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "W": round(self.w, 6),
            "chi_square": round(self.chi_square, 6),
            "df": self.degrees_of_freedom,
            "significant_at_0.05": self.significant,
            "reviewers_m": self.reviewers,
            "objects_n": self.objects,
            "tie_correction": round(self.tie_correction, 6),
        }


def _midranks(values: Sequence[float]) -> list[float]:
    """Average ranks for a single reviewer, ties resolved by midrank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2.0 + 1.0  # ranks are 1-based
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def _chi2_critical(df: int, alpha: float = 0.05) -> float:
    if alpha == 0.05 and df in _CHI2_005:
        return _CHI2_005[df]
    if df <= 0:
        return float("inf")
    # Wilson-Hilferty approximation, adequate for df > 30.
    z = 1.6449 if alpha == 0.05 else 1.9599
    return df * (1.0 - 2.0 / (9.0 * df) + z * (2.0 / (9.0 * df)) ** 0.5) ** 3


def kendalls_w(
    rankings: Sequence[Sequence[float]],
    alpha: float = 0.05,
) -> KendallResult:
    """Kendall's W over ``m`` reviewers x ``n`` objects.

    ``rankings[i][j]`` is reviewer ``i``'s score/rank for object ``j``; higher is better.
    Returns ``W = 0.0`` (and ``significant = False``) for degenerate cohorts where
    ``m < 2`` or ``n < 2`` or the denominator collapses.
    """
    if not rankings:
        return KendallResult(0.0, 0.0, 0, False, 0, 0, 0.0)
    n = len(rankings[0])
    for row in rankings:
        if len(row) != n:
            raise ValueError("every reviewer must rank the same number of objects")
    m = len(rankings)
    if m < 2 or n < 2:
        return KendallResult(0.0, 0.0, max(n - 1, 0), False, m, n, 0.0)

    rank_sums = [0.0] * n
    tie_correction = 0.0
    for row in rankings:
        midranks = _midranks([float(v) for v in row])
        for j, r in enumerate(midranks):
            rank_sums[j] += r
        # Each reviewer contributes each *distinct* tied group once: sum(t^3 - t).
        counts: dict[float, int] = {}
        for value in row:
            counts[float(value)] = counts.get(float(value), 0) + 1
        tie_correction += sum(t ** 3 - t for t in counts.values() if t > 1)

    mean_rank = m * (n + 1) / 2.0
    s = sum((r - mean_rank) ** 2 for r in rank_sums)
    denominator = (m ** 2) * (n ** 3 - n) - m * tie_correction
    if denominator <= 0:
        return KendallResult(0.0, 0.0, n - 1, False, m, n, tie_correction)
    w = 12.0 * s / denominator
    w = min(max(w, 0.0), 1.0)
    df = n - 1
    chi_square = m * (n - 1) * w
    return KendallResult(
        w=w,
        chi_square=chi_square,
        degrees_of_freedom=df,
        significant=chi_square > _chi2_critical(df, alpha),
        reviewers=m,
        objects=n,
        tie_correction=tie_correction,
    )
