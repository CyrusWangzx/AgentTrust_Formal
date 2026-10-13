"""Aggregation + tri-level decision tests (spec 2.3, 2.4).

These are the boundary cases the work order calls out explicitly:
empty trajectories, single-step actions, unanimous cohorts (D_rel -> 0), total
disagreement, missing / zero ``D_base``, odd and even validator counts.
"""

from __future__ import annotations

import pytest

from divergence import (
    DEFAULT_WEIGHTS,
    THETA_HIGH,
    THETA_LOW,
    Decision,
    DBaseInvalid,
    Verdict,
    aggregate_total,
    decide,
    divergence,
    relative_divergence,
)


def make_verdict(
    agent: str,
    *,
    actions: list[str] | None = None,
    trajectory: list[list[float]] | None = None,
    terminal: list[float] | None = None,
    response: int = 90,
    error: str | None = None,
) -> Verdict:
    return Verdict(
        agent=agent,
        actions=actions if actions is not None else ["move", "grip"],
        trajectory=trajectory if trajectory is not None else [[0.0], [1.0]],
        terminal=terminal if terminal is not None else [1.0, 0.0],
        response=response,
        error=error,
    )


class TestAggregateTotal:
    def test_spec_weights(self) -> None:
        assert DEFAULT_WEIGHTS == (0.4, 0.3, 0.3)
        assert aggregate_total(1.0, 1.0, 1.0) == pytest.approx(1.0)

    def test_weighted_mix(self) -> None:
        assert aggregate_total(1.0, 0.0, 0.0) == pytest.approx(0.4)
        assert aggregate_total(0.0, 2.0, 0.0) == pytest.approx(0.6)
        assert aggregate_total(0.0, 0.0, 5.0) == pytest.approx(1.5)

    def test_weights_must_sum_to_one(self) -> None:
        with pytest.raises(ValueError):
            aggregate_total(1.0, 1.0, 1.0, (0.5, 0.3, 0.3))

    def test_negative_component_rejected(self) -> None:
        with pytest.raises(ValueError):
            aggregate_total(-1.0, 0.0, 0.0)


class TestRelativeDivergence:
    def test_ratio(self) -> None:
        assert relative_divergence(3.0, 1.5) == pytest.approx(2.0)

    def test_zero_baseline_raises(self) -> None:
        with pytest.raises(DBaseInvalid):
            relative_divergence(1.0, 0)

    def test_negative_baseline_raises(self) -> None:
        with pytest.raises(DBaseInvalid):
            relative_divergence(1.0, -2.0)

    def test_missing_baseline_raises(self) -> None:
        with pytest.raises(DBaseInvalid):
            relative_divergence(1.0, None)

    def test_boolean_baseline_rejected(self) -> None:
        with pytest.raises(DBaseInvalid):
            relative_divergence(1.0, True)


class TestDecide:
    def test_thresholds_are_frozen_spec_values(self) -> None:
        assert THETA_LOW == 1.5
        assert THETA_HIGH == 3.0

    @pytest.mark.parametrize(
        ("d_rel", "expected"),
        [
            (0.0, Decision.APPROVED),
            (1.0, Decision.APPROVED),
            (1.5, Decision.APPROVED),          # boundary is inclusive
            (1.5000001, Decision.REHEARSE),
            (2.0, Decision.REHEARSE),
            (3.0, Decision.REHEARSE),          # boundary is inclusive
            (3.0000001, Decision.REJECTED),
            (10.0, Decision.REJECTED),
        ],
    )
    def test_tri_level_mapping(self, d_rel: float, expected: Decision) -> None:
        assert decide(d_rel) is expected

    def test_significant_concordance_escalates(self) -> None:
        assert decide(5.0, kendall_significant=True) is Decision.ESCALATED
        assert decide(5.0, kendall_significant=False) is Decision.REJECTED
        assert decide(5.0, kendall_significant=None) is Decision.REJECTED

    def test_negative_divergence_clamped(self) -> None:
        assert decide(-5.0) is Decision.APPROVED

    def test_inverted_thresholds_rejected(self) -> None:
        with pytest.raises(ValueError):
            decide(1.0, theta_low=3.0, theta_high=1.0)


class TestDivergence:
    def test_unanimous_cohort_drel_is_zero_then_approved(self) -> None:
        cohort = [make_verdict(f"v{i}") for i in range(3)]
        decision, reading = divergence(cohort, d_base=0.4)
        assert reading.d_disc == 0.0
        assert reading.d_traj == pytest.approx(0.0)
        assert reading.d_end == pytest.approx(0.0)
        assert reading.d_total == pytest.approx(0.0)
        assert reading.d_rel == pytest.approx(0.0)
        assert decision is Decision.APPROVED

    def test_total_disagreement(self) -> None:
        cohort = [
            make_verdict("a", actions=["x", "y"], trajectory=[[0.0], [0.0]], terminal=[0.0]),
            make_verdict("b", actions=["p", "q"], trajectory=[[9.0], [9.0]], terminal=[9.0]),
        ]
        decision, reading = divergence(cohort, d_base=1.0)
        assert reading.d_disc == pytest.approx(1.0)
        assert reading.d_traj == pytest.approx(9.0)
        assert reading.d_end == pytest.approx(9.0)
        assert reading.d_total == pytest.approx(0.4 * 1.0 + 0.3 * 9.0 + 0.3 * 9.0)
        assert decision is Decision.REJECTED

    def test_empty_trajectories_are_penalised_not_crashing(self) -> None:
        cohort = [
            make_verdict("a", trajectory=[]),
            make_verdict("b", trajectory=[[0.0], [1.0]]),
        ]
        _, reading = divergence(cohort, d_base=1.0)
        assert reading.d_traj == pytest.approx(1.0)
        assert "degenerate trajectory penalised at 1.0" in reading.degraded

    def test_single_step_action_sequences(self) -> None:
        cohort = [
            make_verdict("a", actions=["move"], trajectory=[[1.0]], terminal=[1.0]),
            make_verdict("b", actions=["stop"], trajectory=[[1.0]], terminal=[1.0]),
        ]
        _, reading = divergence(cohort, d_base=1.0)
        assert reading.d_disc == pytest.approx(1.0)
        assert reading.d_traj == pytest.approx(0.0)

    @pytest.mark.parametrize("count", [2, 3, 4, 5])
    def test_odd_and_even_cohorts(self, count: int) -> None:
        cohort = [make_verdict(f"v{i}") for i in range(count)]
        decision, reading = divergence(cohort, d_base=0.5)
        assert reading.cohort_size == count
        assert reading.d_total == pytest.approx(0.0)
        assert decision is Decision.APPROVED

    def test_insufficient_validators(self) -> None:
        cohort = [
            make_verdict("a"),
            make_verdict("b", error="connection reset"),
        ]
        decision, reading = divergence(cohort, d_base=1.0)
        assert decision is Decision.INSUFFICIENT_VALIDATORS
        assert reading.cohort_size == 1

    def test_insufficient_validators_when_cohort_empty(self) -> None:
        decision, _ = divergence([], d_base=1.0)
        assert decision is Decision.INSUFFICIENT_VALIDATORS

    def test_zero_dbase_returns_insufficient_baseline_not_crash(self) -> None:
        cohort = [make_verdict(f"v{i}") for i in range(3)]
        decision, reading = divergence(cohort, d_base=0.0)
        assert decision is Decision.INSUFFICIENT_BASELINE
        assert reading.d_rel is None
        assert "D_base missing or <= 0" in reading.degraded

    def test_missing_dbase_returns_insufficient_baseline(self) -> None:
        cohort = [make_verdict(f"v{i}") for i in range(3)]
        decision, reading = divergence(cohort, d_base=None)
        assert decision is Decision.INSUFFICIENT_BASELINE
        assert reading.d_base is None

    def test_reading_serialises(self) -> None:
        cohort = [make_verdict(f"v{i}") for i in range(3)]
        _, reading = divergence(cohort, d_base=0.5)
        payload = reading.as_dict()
        assert payload["weights"] == {"w1_disc": 0.4, "w2_traj": 0.3, "w3_end": 0.3}
        assert payload["kendall"] is not None

    def test_mahalanobis_terminal_metric(self) -> None:
        cohort = [
            make_verdict("a", terminal=[0.0, 0.0]),
            make_verdict("b", terminal=[1.0, 1.0]),
            make_verdict("c", terminal=[0.5, 2.0]),
        ]
        _, reading = divergence(cohort, d_base=1.0, terminal_metric="mahalanobis")
        assert reading.terminal_metric == "mahalanobis"
        assert reading.d_end >= 0.0
