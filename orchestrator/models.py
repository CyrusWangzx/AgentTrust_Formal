"""Shared dataclasses for one validation request and its rounds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from divergence.core import Decision, DivergenceReading
from divergence.verdict import Verdict
from validators.base import TaskRequest


@dataclass
class RoundOutcome:
    """Everything one rehearsal round produced."""

    round_index: int
    decision: Decision
    reading: DivergenceReading
    verdicts: list[Verdict]

    @property
    def d_rel(self) -> float | None:
        return self.reading.d_rel

    def as_dict(self) -> dict[str, Any]:
        return {
            "round": self.round_index,
            "decision": self.decision.value,
            "divergence": self.reading.as_dict(),
            "verdicts": [v.to_json() for v in self.verdicts],
        }


@dataclass
class ValidationRecord:
    """The full record of a validation request: every round plus the terminal decision.

    This object is what gets hashed, written to the on-chain registry and rendered by the
    frontend panel. It is deliberately JSON-round-trippable end to end.
    """

    validation_id: str
    task: TaskRequest
    cohort: list[dict[str, str]]
    rounds: list[RoundOutcome] = field(default_factory=list)
    final_decision: Decision | None = None
    d_base: float | None = None
    d_total: float | None = None
    d_rel: float | None = None
    escalation_reason: str = ""
    chain: dict[str, Any] = field(default_factory=dict)
    monitoring: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    heterogeneity: dict[str, Any] = field(default_factory=dict)
    cohort_mode: str = "auto"
    #: K from spec §2.4 - the round budget this request ran under. Carried on the record so a
    #: reader can tell "converged in 2 of 3 rounds" from "converged in 2 of 2".
    k_rounds: int = 3

    @property
    def round_count(self) -> int:
        return len(self.rounds)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "agenttrust.validation-record/v1",
            "validationId": self.validation_id,
            "task": {
                "task_id": self.task.task_id,
                "description": self.task.description,
                "proposed_actions": self.task.actions,
                "constraints": self.task.constraints,
                "observation_space": self.task.observation_space,
                "max_steps": self.task.max_steps,
            },
            "cohort": self.cohort,
            "cohort_mode": self.cohort_mode,
            "heterogeneity": self.heterogeneity,
            "d_base": self.d_base,
            "d_total": None if self.d_total is None else round(self.d_total, 6),
            "d_rel": None if self.d_rel is None else round(self.d_rel, 6),
            "rounds": [r.as_dict() for r in self.rounds],
            "round_count": self.round_count,
            "kRounds": self.k_rounds,
            "final_decision": None if self.final_decision is None else self.final_decision.value,
            "escalation_reason": self.escalation_reason,
            "monitoring": self.monitoring,
            "chain": self.chain,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
