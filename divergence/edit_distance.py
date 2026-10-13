"""Discrete action layer: normalized Levenshtein edit distance.

Spec section 2.3:

    d_disc(s_i, s_j) = Lev(s_i, s_j) / max(|s_i|, |s_j|)
    D_disc = (2 / (N(N-1))) * sum_{i<j} d_disc(s_i, s_j)

Token equality is exact by default. Callers may pass a ``normalize`` hook to canonicalise
action tokens (e.g. strip volatile argument ordering) before comparison -- the hook is
applied to the tokens, not to the sequence, so ``|s|`` stays the action count.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")

#: Distance assigned when exactly one of the two sequences is empty. An empty action
#: sequence is a degenerate rehearsal; comparing it against a real plan is maximal
#: disagreement, and 1.0 is the natural ceiling of a normalized edit distance.
DEGENERATE_SEQUENCE_DISTANCE = 1.0


def levenshtein(a: Sequence[T], b: Sequence[T]) -> int:
    """Plain Levenshtein distance (insert / delete / substitute) over any sequences.

    Uses rolling rows: O(min(|a|, |b|)) extra memory.
    """
    if a is b:
        return 0
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    if n < m:  # keep the inner loop on the shorter sequence
        a, b = b, a
        n, m = m, n
    previous = list(range(m + 1))
    current = [0] * (m + 1)
    for i in range(1, n + 1):
        current[0] = i
        ai = a[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ai == b[j - 1] else 1
            current[j] = min(
                previous[j] + 1,        # deletion
                current[j - 1] + 1,     # insertion
                previous[j - 1] + cost,  # substitution / match
            )
        previous, current = current, previous
    return previous[m]


def edit_distance_norm(
    a: Sequence[T],
    b: Sequence[T],
    normalize: Callable[[T], object] | None = None,
) -> float:
    """Normalized edit distance in ``[0, 1]``.

    ``Lev(a, b) / max(|a|, |b|)``. Both sequences empty yields ``0.0`` (agreement on
    "nothing to do"); exactly one empty yields :data:`DEGENERATE_SEQUENCE_DISTANCE`.
    """
    if normalize is not None:
        a = [normalize(t) for t in a]  # type: ignore[assignment]
        b = [normalize(t) for t in b]  # type: ignore[assignment]
    n, m = len(a), len(b)
    if n == 0 and m == 0:
        return 0.0
    if n == 0 or m == 0:
        return DEGENERATE_SEQUENCE_DISTANCE
    return levenshtein(a, b) / max(n, m)


def sequence_divergence(
    sequences: Iterable[Sequence[T]],
    normalize: Callable[[T], object] | None = None,
) -> float:
    """``D_disc``: mean pairwise normalized edit distance over a cohort.

    ``(2 / (N(N-1))) * sum_{i<j} d_disc``. A cohort of 0 or 1 rehearsal yields ``0.0``
    (a single witness cannot disagree with itself); the orchestrator is responsible for
    enforcing the "at least 2 usable validators" rule before calling this.
    """
    seqs = [list(s) for s in sequences]
    k = len(seqs)
    if k < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for i in range(k):
        for j in range(i + 1, k):
            total += edit_distance_norm(seqs[i], seqs[j], normalize=normalize)
            pairs += 1
    return total / pairs
