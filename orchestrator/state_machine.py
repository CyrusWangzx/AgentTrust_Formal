"""K-round escalation state machine (spec 2.4).

Pure logic, no I/O, so the whole branch space is unit-testable without any model or chain.

Transition table, given a round outcome with decision ``d`` and ``K = max_rounds``:

    Approved              -> FINAL(Approved)                     (放行)
    Rejected              -> FINAL(Rejected)                     (拒绝)
    Escalated             -> FINAL(Escalated)                    (转人工)
    InsufficientValidators-> FINAL(InsufficientValidators)        (fail closed)
    InsufficientBaseline  -> FINAL(InsufficientBaseline)         (fail closed)
    Rehearse              -> REHEARSE while round_index < K
                             FINAL(Escalated) once round_index == K   (K 轮耗尽 -> 转人工)

Optional early stop: when ``early_stop_on_regression`` is set, two consecutive rounds whose
``D_rel`` fails to improve trigger FINAL(Escalated) before K is exhausted, instead of burning
the remaining rounds. Recorded in ``escalation_reason`` so the panel can explain why.

Note ``round_index`` is 1-based: after the first round ``round_index == 1``, so with K = 3 the
machine permits rounds 2 and 3 before escalating on round 3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from divergence.core import Decision

from .models import RoundOutcome


class MachineAction(str, Enum):
    """What the orchestrator should do next."""

    REHEARSE = "Rehearse"
    FINAL = "Final"


@dataclass
class MachineState:
    """Immutable-ish view of the machine after each round."""

    max_rounds: int = 3
    early_stop_on_regression: bool = True
    round_index: int = 0
    history: list[RoundOutcome] = field(default_factory=list)
    final_decision: Decision | None = None
    escalation_reason: str = ""

    @property
    def terminal(self) -> bool:
        return self.final_decision is not None

    @property
    def d_rel_trend(self) -> list[float | None]:
        return [r.d_rel for r in self.history]

    def as_dict(self) -> dict[str, object]:
        return {
            "max_rounds": self.max_rounds,
            "round_index": self.round_index,
            "terminal": self.terminal,
            "final_decision": None if self.final_decision is None else self.final_decision.value,
            "escalation_reason": self.escalation_reason,
            "d_rel_trend": self.d_rel_trend,
        }


def _regressed(state: MachineState) -> bool:
    """True when the last two rounds both failed to reduce ``D_rel``."""
    values = [r.d_rel for r in state.history if r.d_rel is not None]
    if len(values) < 3:
        return False
    return values[-1] >= values[-2] >= values[-3] and values[-1] > 0


def advance(state: MachineState, outcome: RoundOutcome) -> tuple[MachineState, MachineAction]:
    """Feed one round outcome into the machine and return the next action."""
    if state.terminal:
        raise RuntimeError("state machine is already terminal; no further rounds are permitted")

    state.history.append(outcome)
    state.round_index = outcome.round_index
    decision = outcome.decision

    if decision is Decision.APPROVED:
        state.final_decision = Decision.APPROVED
        state.escalation_reason = "converged: D_rel within the theta_low band"
        return state, MachineAction.FINAL

    if decision is Decision.REJECTED:
        state.final_decision = Decision.REJECTED
        state.escalation_reason = "D_rel above theta_high without a significant W"
        return state, MachineAction.FINAL

    if decision is Decision.ESCALATED:
        state.final_decision = Decision.ESCALATED
        state.escalation_reason = "D_rel above theta_high with a significant Kendall W"
        return state, MachineAction.FINAL

    if decision is Decision.INSUFFICIENT_VALIDATORS:
        state.final_decision = Decision.INSUFFICIENT_VALIDATORS
        state.escalation_reason = "fewer than 2 usable validators; failing closed"
        return state, MachineAction.FINAL

    if decision is Decision.INSUFFICIENT_BASELINE:
        state.final_decision = Decision.INSUFFICIENT_BASELINE
        state.escalation_reason = "D_base missing or <= 0; refusing to scale the divergence"
        return state, MachineAction.FINAL

    # Decision.REHEARSE
    if state.early_stop_on_regression and _regressed(state):
        state.final_decision = Decision.ESCALATED
        state.escalation_reason = (
            "three consecutive rounds without a D_rel improvement; escalating early"
        )
        return state, MachineAction.FINAL

    if outcome.round_index >= state.max_rounds:
        state.final_decision = Decision.ESCALATED
        state.escalation_reason = (
            f"K rounds exhausted ({outcome.round_index}/{state.max_rounds}) without convergence; "
            "routing to a human"
        )
        return state, MachineAction.FINAL

    state.escalation_reason = (
        f"partial convergence (D_rel={outcome.d_rel}); round "
        f"{outcome.round_index + 1}/{state.max_rounds}"
    )
    return state, MachineAction.REHEARSE


class RoundStateMachine:
    """Thin object wrapper around :func:`advance` for use by the orchestrator."""

    def __init__(self, max_rounds: int = 3, *, early_stop_on_regression: bool = True) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.state = MachineState(
            max_rounds=max_rounds, early_stop_on_regression=early_stop_on_regression
        )

    def record(self, outcome: RoundOutcome) -> MachineAction:
        _, action = advance(self.state, outcome)
        return action

    @property
    def terminal(self) -> bool:
        return self.state.terminal

    @property
    def final_decision(self) -> Decision | None:
        return self.state.final_decision

    @property
    def round_index(self) -> int:
        return self.state.round_index
