"""Threshold calibration slot: ROC + Youden's J (spec 2.4, non-blocking).

Spec section 2.4 freezes ``theta_low = 1.5`` / ``theta_high = 3.0`` for the hackathon build
and defers re-calibration to a PoC calibration set of known-safe vs known-boundary actions.

This module is intentionally a working-but-unwired implementation so the pipeline never
depends on it:

* it runs and is unit-tested,
* it is **not** imported by ``orchestrator`` or ``divergence.core``,
* ``calibrate_thresholds()`` returns the frozen defaults when no calibration set is supplied.

TODO(agenttrust): replace the synthetic sweep below with the real calibration set
(``docs/calibration_set.json``) and publish the ROC curve + Youden J in the paper. Tracked
as task T-CAL-1 in ``docs/ROADMAP.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .core import THETA_HIGH, THETA_LOW


@dataclass(frozen=True)
class RocPoint:
    threshold: float
    tpr: float
    fpr: float
    youden_j: float


@dataclass(frozen=True)
class CalibrationResult:
    theta_low: float
    theta_high: float
    calibrated: bool
    points: tuple[RocPoint, ...] = ()
    note: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "theta_low": self.theta_low,
            "theta_high": self.theta_high,
            "calibrated": self.calibrated,
            "note": self.note,
            "roc": [
                {"threshold": round(p.threshold, 6), "tpr": round(p.tpr, 6),
                 "fpr": round(p.fpr, 6), "youden_j": round(p.youden_j, 6)}
                for p in self.points
            ],
        }


def roc_curve(
    scores: Sequence[float],
    labels: Sequence[int],
) -> tuple[RocPoint, ...]:
    """ROC points for ``scores`` against binary ``labels`` (1 = should be rejected).

    The divergence score is the positive-class score: higher ``D_rel`` means the round
    *should* have been blocked.
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must be the same length")
    positives = sum(1 for y in labels if y == 1)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return ()

    grid = sorted({float(s) for s in scores})
    points: list[RocPoint] = []
    for threshold in grid:
        tp = sum(1 for s, y in zip(scores, labels) if s >= threshold and y == 1)
        fp = sum(1 for s, y in zip(scores, labels) if s >= threshold and y == 0)
        tpr = tp / positives
        fpr = fp / negatives
        points.append(RocPoint(threshold, tpr, fpr, tpr - fpr))
    return tuple(points)


def youden_threshold(points: Iterable[RocPoint]) -> float | None:
    """Threshold maximizing Youden's J = TPR - FPR (ties resolved to the lowest value)."""
    best: RocPoint | None = None
    for point in points:
        if best is None or point.youden_j > best.youden_j:
            best = point
        elif best is not None and point.youden_j == best.youden_j and point.threshold < best.threshold:
            best = point
    return None if best is None else best.threshold


def calibrate_thresholds(
    scores: Sequence[float] | None = None,
    labels: Sequence[int] | None = None,
) -> CalibrationResult:
    """Return the active thresholds.

    With no calibration set (the default for this build) the spec-frozen values are
    returned unchanged, so calling this never mutates behaviour.
    """
    if scores is None or labels is None:
        return CalibrationResult(
            theta_low=THETA_LOW,
            theta_high=THETA_HIGH,
            calibrated=False,
            note="spec-frozen thresholds; supply a calibration set to re-calibrate",
        )
    points = roc_curve(scores, labels)
    low = youden_threshold(points)
    if low is None:
        return CalibrationResult(
            theta_low=THETA_LOW, theta_high=THETA_HIGH, calibrated=False,
            note="calibration set degenerate (single-class); frozen thresholds kept",
        )
    # theta_high stays anchored at the frozen ratio until the PoC set lands.
    ratio = THETA_HIGH / THETA_LOW
    return CalibrationResult(
        theta_low=low, theta_high=low * ratio, calibrated=True,
        points=points,
        note="theta_low from Youden's J; theta_high kept at the frozen 2.0x ratio",
    )


if __name__ == "__main__":  # pragma: no cover - manual convenience entry point
    import json

    print(json.dumps(calibrate_thresholds().as_dict(), indent=2))
