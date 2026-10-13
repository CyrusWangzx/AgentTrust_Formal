"""Aggregation and tri-level decision.

Spec section 2.3 / 2.4 (single source of truth):

    D_total = 0.4 * D_disc + 0.3 * D_traj + 0.3 * D_end
    D_rel   = D_total / D_base

    D_rel <= theta_low (1.5)                  -> Approved
    theta_low < D_rel <= theta_high (3.0)     -> rehearse / weighted re-judgement
    D_rel >  theta_high (3.0)                 -> Rejected / escalate to a human

The thresholds ``theta_low = 1.5`` and ``theta_high = 3.0`` are the frozen values from the
spec. They are meant to be re-calibrated with ROC + Youden's J on a PoC calibration set;
``calibrate.py`` holds that slot and is explicitly non-blocking (see its TODO).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from .distance import terminal_divergence
from .dtw import pairwise_mean, trajectory_divergence
from .edit_distance import sequence_divergence
from .errors import DBaseInvalid
from .kendall import KendallResult, kendalls_w
from .verdict import Verdict, usable_verdicts

#: Frozen aggregation weights ``w = (w1, w2, w3)`` for (disc, traj, end).
DEFAULT_WEIGHTS: tuple[float, float, float] = (0.4, 0.3, 0.3)

#: Frozen decision thresholds on the relative divergence ``D_rel``.
THETA_LOW: float = 1.5
THETA_HIGH: float = 3.0

#: Minimum usable validators required before a cohort may issue a verdict (spec 2.6).
MIN_USABLE_VALIDATORS: int = 2


class Decision(str, Enum):
    """Terminal state of one validation round."""

    APPROVED = "Approved"
    REHEARSE = "Rehearse"
    REJECTED = "Rejected"
    ESCALATED = "Escalated"
    INSUFFICIENT_VALIDATORS = "InsufficientValidators"
    INSUFFICIENT_BASELINE = "InsufficientBaseline"


@dataclass
class DivergenceReading:
    """One row of the divergence ledger, mirrored on-chain by the registry."""

    d_disc: float
    d_traj: float
    d_end: float
    d_total: float
    d_base: float | None
    d_rel: float | None
    weights: tuple[float, float, float] = DEFAULT_WEIGHTS
    cohort_size: int = 0
    terminal_metric: str = "l2"
    kendall: KendallResult | None = None
    degraded: list[str] = field(default_factory=list)
    """Documented degradations applied (e.g. degenerate trajectories penalised)."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "D_disc": round(self.d_disc, 6),
            "D_traj": round(self.d_traj, 6),
            "D_end": round(self.d_end, 6),
            "D_total": round(self.d_total, 6),
            "D_base": None if self.d_base is None else round(self.d_base, 6),
            "D_rel": None if self.d_rel is None else round(self.d_rel, 6),
            "weights": {"w1_disc": self.weights[0], "w2_traj": self.weights[1], "w3_end": self.weights[2]},
            "cohort_size": self.cohort_size,
            "terminal_metric": self.terminal_metric,
            "kendall": self.kendall.as_dict() if self.kendall else None,
            "degraded": list(self.degraded),
        }


def aggregate_total(
    d_disc: float,
    d_traj: float,
    d_end: float,
    weights: Sequence[float] = DEFAULT_WEIGHTS,
) -> float:
    """``D_total = w1*D_disc + w2*D_traj + w3*D_end`` with weight validation."""
    if len(weights) != 3:
        raise ValueError("weights must be a 3-tuple (w1_disc, w2_traj, w3_end)")
    w1, w2, w3 = (float(w) for w in weights)
    for name, w in (("w1", w1), ("w2", w2), ("w3", w3)):
        if w < 0:
            raise ValueError(f"{name} must be non-negative, got {w}")
    if abs(w1 + w2 + w3 - 1.0) > 1e-9:
        raise ValueError(f"weights must sum to 1.0, got {w1 + w2 + w3}")
    components = (float(d_disc), float(d_traj), float(d_end))
    for name, value in zip(("D_disc", "D_traj", "D_end"), components):
        if value < 0:
            raise ValueError(f"{name} must be non-negative, got {value}")
    return w1 * components[0] + w2 * components[1] + w3 * components[2]


def relative_divergence(d_total: float, d_base: float | None) -> float:
    """``D_rel = D_total / D_base``.

    Raises :class:`DBaseInvalid` when ``D_base`` is ``None`` or ``<= 0`` -- the divide-by-zero
    guard required by spec 2.3. The orchestrator converts that into
    :attr:`Decision.INSUFFICIENT_BASELINE` rather than guessing a baseline.
    """
    if d_base is None or not isinstance(d_base, (int, float)) or isinstance(d_base, bool):
        raise DBaseInvalid(d_base)
    if d_base <= 0:
        raise DBaseInvalid(d_base)
    return float(d_total) / float(d_base)


def decide(
    d_rel: float,
    theta_low: float = THETA_LOW,
    theta_high: float = THETA_HIGH,
    kendall_significant: bool | None = None,
) -> Decision:
    """Map ``D_rel`` to the tri-level outcome.

    ``kendall_significant`` only matters above ``theta_high``: spec 3.2.3 escalates to a
    human when the cohort's ordering disagreement is also statistically significant
    (``chi^2 = m(n-1)W``), otherwise the round is a plain rejection.
    """
    if theta_high < theta_low:
        raise ValueError("theta_high must be >= theta_low")
    value = max(float(d_rel), 0.0)
    if value <= theta_low:
        return Decision.APPROVED
    if value <= theta_high:
        return Decision.REHEARSE
    return Decision.ESCALATED if kendall_significant else Decision.REJECTED


def divergence(
    verdicts: Iterable[Verdict],
    d_base: float | None,
    weights: Sequence[float] = DEFAULT_WEIGHTS,
    terminal_metric: str = "l2",
    action_normalize: Any = None,
    min_validators: int = MIN_USABLE_VALIDATORS,
    theta_low: float = THETA_LOW,
    theta_high: float = THETA_HIGH,
) -> tuple[Decision, DivergenceReading]:
    """Compute the full divergence reading and the tri-level outcome for a cohort.

    Returns ``(Decision, DivergenceReading)``. ``INSUFFICIENT_VALIDATORS`` and
    ``INSUFFICIENT_BASELINE`` short-circuit before any decision is made; in those cases the
    reading still carries whatever layer values were computable so the panel can show why.
    """
    cohort = usable_verdicts(list(verdicts))
    degraded: list[str] = []
    if len(cohort) < min_validators:
        return Decision.INSUFFICIENT_VALIDATORS, DivergenceReading(
            d_disc=0.0, d_traj=0.0, d_end=0.0, d_total=0.0, d_base=d_base, d_rel=None,
            weights=tuple(weights),  # type: ignore[arg-type]
            cohort_size=len(cohort), terminal_metric=terminal_metric,
            degraded=[f"usable validators {len(cohort)} < required {min_validators}"],
        )

    actions = [v.actions for v in cohort]
    trajectories = [v.trajectory for v in cohort]
    terminals = [v.terminal for v in cohort]

    if any(len(v.trajectory) == 0 for v in cohort):
        degraded.append("degenerate trajectory penalised at 1.0")
    if any(v.terminal is None for v in cohort):
        degraded.append("missing terminal state penalised at 1.0")

    d_disc = sequence_divergence(actions, normalize=action_normalize)
    d_traj = trajectory_divergence(trajectories)
    d_end = terminal_divergence(terminals, metric=terminal_metric)
    d_total = aggregate_total(d_disc, d_traj, d_end, weights)

    # Concordance cross-check: rank the cohort by their ERC-8004 response scores across
    # a fixed set of criteria so W has n >= 2 objects to order.
    kendall = kendalls_w(_concordance_matrix(cohort))

    try:
        d_rel = relative_divergence(d_total, d_base)
    except DBaseInvalid:
        return Decision.INSUFFICIENT_BASELINE, DivergenceReading(
            d_disc=d_disc, d_traj=d_traj, d_end=d_end, d_total=d_total,
            d_base=d_base, d_rel=None, weights=tuple(weights),  # type: ignore[arg-type]
            cohort_size=len(cohort), terminal_metric=terminal_metric,
            kendall=kendall, degraded=degraded + ["D_base missing or <= 0"],
        )

    reading = DivergenceReading(
        d_disc=d_disc, d_traj=d_traj, d_end=d_end, d_total=d_total,
        d_base=float(d_base), d_rel=d_rel, weights=tuple(weights),  # type: ignore[arg-type]
        cohort_size=len(cohort), terminal_metric=terminal_metric,
        kendall=kendall, degraded=degraded,
    )
    return decide(d_rel, theta_low, theta_high, kendall.significant), reading


def _concordance_matrix(cohort: Sequence[Verdict]) -> list[list[float]]:
    """Build the ``m x n`` matrix Kendall's W consumes.

    Reviewers are the cohort members; the ranked objects are the fixed criteria
    ``(response score, plan length, path straightness, terminal magnitude)``. Ranking the
    same cohort on several criteria is what makes ``n = RANKED_OBJECTS >= 2`` and lets ``W``
    describe how coherent the cohort's internal ordering is.
    """
    return [
        [
            float(v.response),
            float(len(v.actions)),
            _path_straightness(v.trajectory),
            _terminal_magnitude(v.terminal),
        ]
        for v in cohort
    ]


def _path_straightness(trajectory: Sequence[Sequence[float]]) -> float:
    if len(trajectory) < 2:
        return 0.0
    direct = _norm([trajectory[-1][k] - trajectory[0][k] for k in range(len(trajectory[0]))])
    travelled = 0.0
    for prev, cur in zip(trajectory, list(trajectory)[1:]):
        travelled += _norm([cur[k] - prev[k] for k in range(len(cur))])
    return 0.0 if travelled == 0 else direct / travelled


def _terminal_magnitude(terminal: Sequence[float] | None) -> float:
    return 0.0 if terminal is None else _norm(terminal)


def _norm(vector: Sequence[float]) -> float:
    return sum(float(v) * float(v) for v in vector) ** 0.5
