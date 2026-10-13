"""K-round escalation state machine tests (spec 2.4).

The work order calls out the "K rounds exhausted" branch explicitly, so it is covered from both
directions: the machine's own transitions, and the orchestrator driving it with a real cohort.
"""

from __future__ import annotations

import pytest

from divergence.core import Decision, DivergenceReading
from orchestrator.models import RoundOutcome
from orchestrator.state_machine import MachineAction, MachineState, RoundStateMachine, advance


def reading(d_rel: float | None, d_total: float = 1.0) -> DivergenceReading:
    return DivergenceReading(
        d_disc=0.1, d_traj=0.1, d_end=0.1, d_total=d_total,
        d_base=0.5, d_rel=d_rel,
    )


def outcome(round_index: int, decision: Decision, d_rel: float | None = 1.0) -> RoundOutcome:
    return RoundOutcome(
        round_index=round_index, decision=decision, reading=reading(d_rel), verdicts=[]
    )


class TestTerminalDecisions:
    @pytest.mark.parametrize(
        ("decision", "reason_fragment"),
        [
            (Decision.APPROVED, "converged"),
            (Decision.REJECTED, "theta_high"),
            (Decision.ESCALATED, "significant Kendall W"),
            (Decision.INSUFFICIENT_VALIDATORS, "failing closed"),
            (Decision.INSUFFICIENT_BASELINE, "D_base missing"),
        ],
    )
    def test_each_non_rehearse_decision_is_immediately_terminal(
        self, decision: Decision, reason_fragment: str
    ) -> None:
        machine = RoundStateMachine(max_rounds=3)
        assert machine.record(outcome(1, decision)) is MachineAction.FINAL
        assert machine.terminal
        assert machine.final_decision is decision
        assert reason_fragment in machine.state.escalation_reason

    def test_rejects_further_rounds_once_terminal(self) -> None:
        machine = RoundStateMachine(max_rounds=3)
        machine.record(outcome(1, Decision.APPROVED))
        with pytest.raises(RuntimeError):
            machine.record(outcome(2, Decision.REHEARSE))


class TestKRoundExhaustion:
    @pytest.mark.parametrize("k", [1, 2, 3, 5])
    def test_escalates_exactly_when_k_is_exhausted(self, k: int) -> None:
        machine = RoundStateMachine(max_rounds=k)
        actions = []
        for index in range(1, k + 1):
            # Strictly decreasing D_rel: still in the rehearsal band, but improving, so the
            # regression early-stop stays out of the way and K is what terminates the loop.
            d_rel = 2.0 + (k - index) * 0.05
            actions.append(machine.record(outcome(index, Decision.REHEARSE, d_rel=d_rel)))
        assert actions[:-1] == [MachineAction.REHEARSE] * (k - 1)
        assert actions[-1] is MachineAction.FINAL
        assert machine.final_decision is Decision.ESCALATED
        assert f"K rounds exhausted ({k}/{k})" in machine.state.escalation_reason

    def test_k_of_three_takes_three_rounds(self) -> None:
        machine = RoundStateMachine(max_rounds=3)
        assert machine.record(outcome(1, Decision.REHEARSE, d_rel=2.5)) is MachineAction.REHEARSE
        assert machine.record(outcome(2, Decision.REHEARSE, d_rel=2.3)) is MachineAction.REHEARSE
        assert machine.record(outcome(3, Decision.REHEARSE, d_rel=2.1)) is MachineAction.FINAL
        assert machine.round_index == 3

    def test_convergence_midway_stops_early(self) -> None:
        machine = RoundStateMachine(max_rounds=5)
        assert machine.record(outcome(1, Decision.REHEARSE, d_rel=2.5)) is MachineAction.REHEARSE
        assert machine.record(outcome(2, Decision.REHEARSE, d_rel=1.9)) is MachineAction.REHEARSE
        assert machine.record(outcome(3, Decision.APPROVED, d_rel=1.2)) is MachineAction.FINAL
        assert machine.final_decision is Decision.APPROVED

    def test_d_rel_trend_is_recorded(self) -> None:
        machine = RoundStateMachine(max_rounds=3)
        machine.record(outcome(1, Decision.REHEARSE, d_rel=2.8))
        machine.record(outcome(2, Decision.REHEARSE, d_rel=2.1))
        machine.record(outcome(3, Decision.REHEARSE, d_rel=2.0))
        assert machine.state.d_rel_trend == [2.8, 2.1, 2.0]


class TestRegressionEarlyStop:
    def test_three_flat_rounds_escalate_before_k(self) -> None:
        machine = RoundStateMachine(max_rounds=9)
        machine.record(outcome(1, Decision.REHEARSE, d_rel=2.0))
        machine.record(outcome(2, Decision.REHEARSE, d_rel=2.0))
        action = machine.record(outcome(3, Decision.REHEARSE, d_rel=2.0))
        assert action is MachineAction.FINAL
        assert "without a D_rel improvement" in machine.state.escalation_reason

    def test_regression_early_stop_can_be_disabled(self) -> None:
        machine = RoundStateMachine(max_rounds=5, early_stop_on_regression=False)
        for index in range(1, 4):
            assert machine.record(outcome(index, Decision.REHEARSE, d_rel=2.0)) is MachineAction.REHEARSE

    def test_non_monotone_trend_does_not_trigger_early_stop(self) -> None:
        machine = RoundStateMachine(max_rounds=5)
        machine.record(outcome(1, Decision.REHEARSE, d_rel=2.0))
        machine.record(outcome(2, Decision.REHEARSE, d_rel=2.4))
        assert machine.record(outcome(3, Decision.REHEARSE, d_rel=2.2)) is MachineAction.REHEARSE


class TestMachineGuards:
    def test_rejects_non_positive_k(self) -> None:
        with pytest.raises(ValueError):
            RoundStateMachine(max_rounds=0)

    def test_free_function_advance_matches_the_wrapper(self) -> None:
        state = MachineState(max_rounds=2)
        _, action = advance(state, outcome(1, Decision.REHEARSE))
        assert action is MachineAction.REHEARSE
        _, action = advance(state, outcome(2, Decision.REHEARSE))
        assert action is MachineAction.FINAL

    def test_state_serialises(self) -> None:
        machine = RoundStateMachine(max_rounds=3)
        machine.record(outcome(1, Decision.APPROVED, d_rel=0.4))
        payload = machine.state.as_dict()
        assert payload["terminal"] is True
        assert payload["final_decision"] == "Approved"
        assert payload["d_rel_trend"] == [0.4]
