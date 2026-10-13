"""The pre-execution rehearsal orchestrator (spec 2.2).

Responsibilities, in order:

1. **fan-out** the task to every cohort member concurrently (they never share context);
2. **collect** verdicts, counting failed/absent agents as unusable;
3. **quantify** divergence (``divergence.divergence``) -> ``D_disc``/``D_traj``/``D_end``,
   ``D_total``, ``D_rel``, Kendall's W;
4. **branch** on the tri-level decision and drive the K-round state machine;
5. **finalise** the record and hand it to the chain writer.

The orchestrator owns flow only. It never scores a rehearsal - the math in ``divergence``
decides, which is what makes the referee un-bribable (plan section 3.2.1).
"""

from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, Sequence

from divergence.core import (
    DEFAULT_WEIGHTS,
    Decision,
    DivergenceReading,
    divergence,
)
from divergence.verdict import Verdict, usable_verdicts
from validators.base import BaseValidator, TaskRequest
from validators.cohort import Cohort, describe_cohort

from .config import Settings
from .hashing import request_hash, request_payload
from .models import RoundOutcome, ValidationRecord
from .state_machine import MachineAction, RoundStateMachine

logger = logging.getLogger("agenttrust.orchestrator")

#: Callback signature for progress streaming (used by scripts/demo and the API server).
Emitter = Callable[[str, dict[str, Any]], None]


class ChainWriter(Protocol):
    """Minimal contract the orchestrator needs from the on-chain layer."""

    def submit(self, record: ValidationRecord) -> dict[str, Any]:
        """Persist/finalise the record and return a chain receipt dict."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_recording_hash(record: ValidationRecord) -> str:
    """bytes32 commitment over the terminal decision and every round's readings."""
    import json

    payload = {
        "validationId": record.validation_id,
        "task_id": record.task.task_id,
        "cohort": [m.get("agent") for m in record.cohort],
        "d_base": record.d_base,
        "d_total": record.d_total,
        "d_rel": record.d_rel,
        "final_decision": None if record.final_decision is None else record.final_decision.value,
        "rounds": [
            {
                "round": r.round_index,
                "decision": r.decision.value,
                "D_disc": r.reading.d_disc,
                "D_traj": r.reading.d_traj,
                "D_end": r.reading.d_end,
                "D_total": r.reading.d_total,
                "D_rel": r.reading.d_rel,
                "verdicts": [v.verdict_hash() for v in r.verdicts],
            }
            for r in record.rounds
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Orchestrator:
    """Runs one validation request from fan-out to finalised record."""

    def __init__(
        self,
        cohort: Cohort,
        settings: Settings,
        *,
        chain_writer: ChainWriter | None = None,
        emitter: Emitter | None = None,
        weights: Sequence[float] = DEFAULT_WEIGHTS,
        terminal_metric: str | None = None,
        max_rounds: int | None = None,
        early_stop_on_regression: bool = True,
        max_workers: int | None = None,
    ) -> None:
        self.cohort = cohort
        self.settings = settings
        self.chain_writer = chain_writer
        self.emitter = emitter
        self.weights = tuple(weights)  # type: ignore[assignment]
        self.terminal_metric = terminal_metric or settings.terminal_metric
        self.max_rounds = max_rounds or cohort.max_rounds or settings.max_rounds
        self.min_usable = max(cohort.min_usable, settings.min_usable_validators)
        self.early_stop_on_regression = early_stop_on_regression
        self.max_workers = max_workers or max(len(cohort.members), 1)

    # ------------------------------------------------------------------ emission
    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.emitter is not None:
            try:
                self.emitter(event, payload)
            except Exception:  # noqa: BLE001 - a broken listener must not kill a validation
                logger.debug("emitter failed for event %s", event, exc_info=True)

    # ------------------------------------------------------------------ fan-out
    def rehearse(self, task: TaskRequest, *, tag: str) -> list[Verdict]:
        """Dispatch the task to every cohort member concurrently.

        Members receive only ``task`` - no shared scratchpad, no peer verdicts. This is the
        information-isolation half of the anti-collusion design (spec 2.5).
        """
        members: list[BaseValidator] = self.cohort.members
        if not members:
            return []
        results: list[Verdict | None] = [None] * len(members)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._safe_rehearse, member, task, tag): index
                for index, member in enumerate(members)
            }
            for future in as_completed(futures):
                index = futures[future]
                verdict = future.result()
                results[index] = verdict
                self._emit(
                    "verdict",
                    {
                        "agent": verdict.agent,
                        "model": verdict.model,
                        "provider": verdict.provider,
                        "response": verdict.response,
                        "usable": verdict.usable,
                        "latency_ms": verdict.latency_ms,
                        "error": verdict.error,
                        "round": task.payload.get("round", 1),
                    },
                )
        return [v for v in results if v is not None]

    @staticmethod
    def _safe_rehearse(member: BaseValidator, task: TaskRequest, tag: str) -> Verdict:
        """Adapters are contractually non-raising; this is the belt to that suspenders."""
        try:
            return member.rehearse(task, tag=tag)
        except Exception as exc:  # noqa: BLE001
            logger.exception("validator %s raised", member.name)
            return member.unavailable_verdict(f"{type(exc).__name__}: {exc}", task, tag)

    # ------------------------------------------------------------------ run
    def run(self, task: TaskRequest) -> ValidationRecord:
        """Execute the full K-round validation and return the finalised record."""
        validation_id = make_validation_id(task, self.cohort)
        started = _now()
        record = ValidationRecord(
            validation_id=validation_id,
            task=task,
            cohort=[m.identity for m in self.cohort.members],
            cohort_mode="offline" if self.cohort.offline else "live",
            heterogeneity=describe_cohort(self.cohort),
            k_rounds=self.max_rounds,
            started_at=started,
        )

        machine = RoundStateMachine(
            max_rounds=self.max_rounds, early_stop_on_regression=self.early_stop_on_regression
        )
        self._emit("validation_started", {
            "validationId": validation_id,
            "task_id": task.task_id,
            "cohort": record.cohort,
            "cohort_mode": record.cohort_mode,
            "max_rounds": self.max_rounds,
        })

        while not machine.terminal:
            round_index = machine.round_index + 1
            tag = (
                self.cohort.settings.get("tag_round_1", "soft")
                if round_index == 1
                else self.cohort.settings.get("tag_round_k", "hard")
            )
            round_task = task.derive_round(round_index)
            self._emit("round_started", {
                "validationId": validation_id,
                "round": round_index,
                "tag": tag,
                "cohort_size": len(self.cohort.members),
            })

            verdicts = self.rehearse(round_task, tag=str(tag))
            decision, reading = divergence(
                verdicts,
                d_base=task.d_base,
                weights=self.weights,
                terminal_metric=self.terminal_metric,
                min_validators=self.min_usable,
                theta_low=self.settings.theta_low,
                theta_high=self.settings.theta_high,
            )
            outcome = RoundOutcome(
                round_index=round_index, decision=decision, reading=reading, verdicts=verdicts
            )
            record.rounds.append(outcome)
            record.d_base = task.d_base

            self._emit("round_scored", {
                "validationId": validation_id,
                "round": round_index,
                **reading.as_dict(),
                "decision": decision.value,
            })

            action = machine.record(outcome)
            if action is MachineAction.FINAL:
                break
            self._emit("round_escalated", {
                "validationId": validation_id,
                "next_round": machine.round_index + 1,
                "reason": machine.state.escalation_reason,
            })

        final = record.rounds[-1] if record.rounds else None
        record.final_decision = machine.final_decision or (final.decision if final else None)
        record.escalation_reason = machine.state.escalation_reason
        if final is not None:
            record.d_total = final.reading.d_total
            record.d_rel = final.reading.d_rel
        record.finished_at = _now()

        self._emit("validation_scored", {
            "validationId": validation_id,
            "final_decision": None if record.final_decision is None else record.final_decision.value,
            "d_total": record.d_total,
            "d_rel": record.d_rel,
            "rounds": record.round_count,
            "escalation_reason": record.escalation_reason,
        })

        if self.chain_writer is not None:
            receipt = self.chain_writer.submit(record)
            record.chain = receipt
            self._emit("chain_written", {"validationId": validation_id, **receipt})

        return record


def make_validation_id(task: TaskRequest, cohort: Cohort) -> str:
    """ERC-8004 ``requestHash`` for a (task, cohort) pair - also AgentTrust's ``validationId``.

    ``keccak256`` of the canonical request payload, as the ERC-8004 Validation Registry
    requires. Deterministic on purpose: re-running the demo with the same task and cohort
    yields the same id, so the registry sees an idempotent key rather than duplicate requests.
    """
    return request_hash(request_payload(task, cohort.names))


def summarise(record: ValidationRecord) -> str:
    """One-line human summary used by the CLI demo."""
    decision = record.final_decision.value if record.final_decision else "None"
    d_rel = "n/a" if record.d_rel is None else f"{record.d_rel:.4f}"
    d_total = "n/a" if record.d_total is None else f"{record.d_total:.4f}"
    return (
        f"{record.validation_id[:10]}... task={record.task.task_id} "
        f"rounds={record.round_count} D_total={d_total} "
        f"D_rel={d_rel} -> {decision}"
    )


def usable_count(verdicts: Sequence[Verdict]) -> int:
    return len(usable_verdicts(verdicts))


__all__ = [
    "Orchestrator",
    "ChainWriter",
    "Emitter",
    "canonical_recording_hash",
    "make_validation_id",
    "summarise",
    "usable_count",
    "Decision",
    "DivergenceReading",
]
