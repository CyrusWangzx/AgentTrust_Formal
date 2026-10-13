"""Typed error hierarchy for the divergence library.

Errors are typed so the orchestrator can branch on them deterministically instead of
string-matching messages.
"""

from __future__ import annotations


class DivergenceError(Exception):
    """Base class for every error raised by the divergence library."""


class DBaseInvalid(DivergenceError):
    """Raised when the task baseline difficulty ``D_base`` is missing or non-positive.

    ``D_rel = D_total / D_base`` is undefined for ``D_base <= 0``. Per spec section
    2.3 the orchestrator must surface this as a distinct state rather than silently
    producing ``inf`` or dividing by zero.
    """

    def __init__(self, d_base: object) -> None:
        super().__init__(
            "D_base must be a positive number to compute D_rel "
            f"(got {d_base!r}); configure a task baseline or let the orchestrator "
            "report INSUFFICIENT_BASELINE"
        )
        self.d_base = d_base


class DegenerateInput(DivergenceError):
    """Raised when an input cannot be meaningfully compared.

    Used by the low-level primitives (``dtw_distance``, ``mahalanobis_distance``) which
    refuse to guess. The vector-level helpers (``trajectory_divergence`` and friends)
    convert degeneracy into an explicit, documented penalty instead of raising, so a
    partially-populated cohort never crashes the orchestration loop.
    """
