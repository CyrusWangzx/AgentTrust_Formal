"""AgentTrust divergence library.

Deterministic, dependency-light implementation of the divergence metrics defined in
AgentTrust spec section 2.3 (the single source of truth for this repository):

    D_disc  normalized edit distance over discrete action sequences
    D_traj  DTW over continuous trajectories (path-length normalized)
    D_end   L2 / Mahalanobis distance over terminal state vectors
    W       Kendall's W coefficient of concordance (chi-square = m(n-1)W)
    D_total 0.4*D_disc + 0.3*D_traj + 0.3*D_end
    D_rel   D_total / D_base

All divergence values are computed off-chain in deterministic code. The on-chain
registry only stores the resulting readings and the final decision.
"""

from .core import (
    DEFAULT_WEIGHTS,
    Decision,
    DivergenceReading,
    THETA_HIGH,
    THETA_LOW,
    aggregate_total,
    decide,
    divergence,
    pairwise_mean,
    relative_divergence,
)
from .dtw import dtw_distance, trajectory_divergence
from .edit_distance import edit_distance_norm, sequence_divergence, levenshtein
from .errors import DBaseInvalid, DegenerateInput, DivergenceError
from .kendall import KendallResult, kendalls_w
from .distance import l2_distance, mahalanobis_distance, terminal_divergence
from .verdict import Verdict, VERDICT_SCHEMA, usable_verdicts

__all__ = [
    # verdict contract
    "Verdict",
    "VERDICT_SCHEMA",
    "usable_verdicts",
    # edit distance layer
    "levenshtein",
    "edit_distance_norm",
    "sequence_divergence",
    # trajectory layer
    "dtw_distance",
    "trajectory_divergence",
    # terminal layer
    "l2_distance",
    "mahalanobis_distance",
    "terminal_divergence",
    # concordance layer
    "kendalls_w",
    "KendallResult",
    # aggregation + decision
    "DEFAULT_WEIGHTS",
    "THETA_LOW",
    "THETA_HIGH",
    "Decision",
    "DivergenceReading",
    "aggregate_total",
    "relative_divergence",
    "pairwise_mean",
    "decide",
    "divergence",
    # errors
    "DivergenceError",
    "DBaseInvalid",
    "DegenerateInput",
]
