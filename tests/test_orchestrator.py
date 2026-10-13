"""Orchestrator tests: fan-out, verdict collection, threshold branching, K-round escalation.

These run entirely offline against deterministic fixtures, so they assert on real divergence
numbers produced by the real code path rather than on mocks.
"""

from __future__ import annotations

import pytest

from divergence.core import Decision
from divergence.verdict import Verdict
from orchestrator.config import Settings
from orchestrator.models import ValidationRecord
from orchestrator.orchestrator import (
    Orchestrator,
    canonical_recording_hash,
    make_validation_id,
    summarise,
)
from validators.base import BaseValidator, TaskRequest
from validators.cohort import Cohort
from validators.simulated import SimulatedValidator


def make_cohort(stances: list[float], *, scale: float = 1.0, prefix: str = "fixture") -> Cohort:
    members: list[BaseValidator] = [
        SimulatedValidator(name=f"{prefix}-{i}", stance=stance, scale=scale)
        for i, stance in enumerate(stances)
    ]
    declarations = [
        {
            "name": m.name,
            "model_family": f"family-{i}",
            "provider": f"endpoint-{i}",
            "framework": f"framework-{i}",
        }
        for i, m in enumerate(members)
    ]
    return Cohort(
        members=members,
        declarations=declarations,
        settings={"max_rounds": 3, "min_usable": 2, "tag_round_1": "soft", "tag_round_k": "hard"},
        offline=True,
    )


def make_task(*, risk: float = 0.0, d_base: float | None = 0.5, actions: int = 4) -> TaskRequest:
    return TaskRequest(
        task_id="unit-task",
        description="unit test task",
        actions=[f"step_{i}()" for i in range(actions)],
        constraints=["stay in bounds"],
        d_base=d_base,
        payload={"risk_fraction": risk},
    )


class FailingValidator(BaseValidator):
    """Adapter that cannot run - used to exercise the INSUFFICIENT_VALIDATORS path."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.model = "unavailable"
        self.provider = "unavailable"
        self.framework = "n/a"
        self.endpoint = "n/a"

    def is_available(self) -> bool:
        return False

    def rehearse(self, task: TaskRequest, *, tag: str = "soft") -> Verdict:
        return self.unavailable_verdict("no credential configured", task, tag)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(chain_id=10143, artifacts_dir=tmp_path / "artifacts")


class TestUnanimousCohort:
    def test_agreement_is_approved_in_one_round(self, settings: Settings) -> None:
        orchestrator = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings)
        record = orchestrator.run(make_task(risk=0.0))
        assert record.round_count == 1
        assert record.final_decision is Decision.APPROVED
        assert record.d_total == pytest.approx(0.0)
        assert record.d_rel == pytest.approx(0.0)

    def test_verdicts_are_collected_for_every_member(self, settings: Settings) -> None:
        orchestrator = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings)
        record = orchestrator.run(make_task())
        verdicts = record.rounds[0].verdicts
        assert len(verdicts) == 3
        assert [v.agent for v in verdicts] == ["fixture-0", "fixture-1", "fixture-2"]
        assert all(v.usable for v in verdicts)


class TestDisagreeingCohort:
    def test_opposing_stances_produce_a_rehearsal_band_reading(self, settings: Settings) -> None:
        orchestrator = Orchestrator(make_cohort([-0.8, 0.0, 0.8]), settings)
        record = orchestrator.run(make_task(risk=0.55))
        assert record.d_total > 0
        assert record.d_rel is not None and record.d_rel > settings.theta_low

    def test_k_rounds_exhausted_escalates_to_a_human(self, settings: Settings) -> None:
        """The work order's K-round branch, driven end to end through the orchestrator."""
        orchestrator = Orchestrator(make_cohort([-0.8, 0.0, 0.8]), settings, max_rounds=3)
        record = orchestrator.run(make_task(risk=0.55))
        assert record.final_decision is Decision.ESCALATED
        assert record.round_count == 3
        assert "K rounds exhausted" in record.escalation_reason

    def test_a_larger_k_keeps_rehearsing(self, settings: Settings) -> None:
        orchestrator = Orchestrator(make_cohort([-0.8, 0.0, 0.8]), settings, max_rounds=2)
        record = orchestrator.run(make_task(risk=0.55))
        assert record.round_count == 2
        assert record.final_decision is Decision.ESCALATED

    def test_follow_up_rounds_reissue_the_task(self, settings: Settings) -> None:
        orchestrator = Orchestrator(make_cohort([-0.8, 0.0, 0.8]), settings, max_rounds=2)
        record = orchestrator.run(make_task(risk=0.55))
        # Each later round gets a round-tagged task id so deterministic fixtures are re-seeded.
        assert record.rounds[0].verdicts[0].rationale != record.rounds[1].verdicts[0].rationale

    def test_high_divergence_above_theta_high_is_not_approved(self, settings: Settings) -> None:
        orchestrator = Orchestrator(make_cohort([-0.95, 0.0, 0.95]), settings)
        record = orchestrator.run(make_task(risk=1.0, d_base=0.35))
        assert record.d_rel is not None and record.d_rel > settings.theta_high
        assert record.final_decision in {Decision.REJECTED, Decision.ESCALATED}


class TestFailClosedPaths:
    def test_insufficient_validators_when_the_cohort_cannot_run(self, settings: Settings) -> None:
        cohort = Cohort(
            members=[SimulatedValidator(name="ok", stance=0.0), FailingValidator("broken-a"), FailingValidator("broken-b")],
            declarations=[],
            settings={"max_rounds": 3, "min_usable": 2},
            offline=True,
        )
        record = Orchestrator(cohort, settings).run(make_task())
        assert record.final_decision is Decision.INSUFFICIENT_VALIDATORS
        assert record.round_count == 1  # fail closed immediately, no pointless re-runs

    def test_insufficient_baseline_when_d_base_is_zero(self, settings: Settings) -> None:
        record = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings).run(make_task(d_base=0.0))
        assert record.final_decision is Decision.INSUFFICIENT_BASELINE
        assert record.d_rel is None

    def test_insufficient_baseline_when_d_base_is_missing(self, settings: Settings) -> None:
        record = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings).run(make_task(d_base=None))
        assert record.final_decision is Decision.INSUFFICIENT_BASELINE

    def test_a_raising_adapter_is_contained(self, settings: Settings) -> None:
        class Exploding(SimulatedValidator):
            def rehearse(self, task: TaskRequest, *, tag: str = "soft") -> Verdict:
                raise RuntimeError("boom")

        cohort = Cohort(
            members=[
                SimulatedValidator(name="ok-a", stance=0.0),
                SimulatedValidator(name="ok-b", stance=0.4),
                Exploding(name="boom", stance=0.0),
            ],
            declarations=[],
            settings={"min_usable": 2, "max_rounds": 3},
            offline=True,
        )
        record = Orchestrator(cohort, settings).run(make_task())
        # Two healthy validators remain, so the round still resolves.
        assert record.final_decision is not None
        failed = [v for v in record.rounds[0].verdicts if not v.usable]
        assert failed and "RuntimeError" in (failed[0].error or "")


class TestEmitterAndChain:
    def test_emitter_receives_the_full_event_stream(self, settings: Settings) -> None:
        events: list[tuple[str, dict]] = []
        orchestrator = Orchestrator(
            make_cohort([0.0, 0.0, 0.0]), settings, emitter=lambda e, p: events.append((e, p))
        )
        orchestrator.run(make_task())
        names = [name for name, _ in events]
        assert names[0] == "validation_started"
        assert "verdict" in names
        assert "round_scored" in names
        assert names[-1] == "validation_scored"

    def test_a_broken_emitter_does_not_break_the_validation(self, settings: Settings) -> None:
        def explode(event: str, payload: dict) -> None:
            raise RuntimeError("listener is broken")

        record = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings, emitter=explode).run(make_task())
        assert record.final_decision is Decision.APPROVED

    def test_chain_writer_receipt_is_attached(self, settings: Settings) -> None:
        class StubWriter:
            def __init__(self) -> None:
                self.records: list[ValidationRecord] = []

            def submit(self, record: ValidationRecord) -> dict:
                self.records.append(record)
                return {"mode": "stub", "txHash": None}

        writer = StubWriter()
        record = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings, chain_writer=writer).run(make_task())
        assert writer.records and writer.records[0] is record
        assert record.chain == {"mode": "stub", "txHash": None}


class TestRecordShape:
    def test_validation_id_is_a_deterministic_erc8004_request_hash(self, settings: Settings) -> None:
        cohort = make_cohort([0.0, 0.0, 0.0])
        task = make_task()
        first = make_validation_id(task, cohort)
        assert first == make_validation_id(task, cohort)
        assert first.startswith("0x") and len(first) == 66

    def test_validation_id_changes_with_the_cohort(self) -> None:
        task = make_task()
        assert make_validation_id(task, make_cohort([0.0, 0.0, 0.0], prefix="alpha")) != make_validation_id(
            task, make_cohort([0.0, 0.0, 0.0], prefix="beta")
        )

    def test_record_serialises_to_json_ready_dict(self, settings: Settings) -> None:
        import json

        record = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings).run(make_task())
        payload = record.as_dict()
        assert payload["schema"] == "agenttrust.validation-record/v1"
        assert payload["final_decision"] == "Approved"
        assert payload["cohort_mode"] == "offline"
        json.dumps(payload)  # must be JSON-serialisable end to end

    def test_record_carries_the_round_budget_it_ran_under(self, settings: Settings) -> None:
        """A reader must be able to tell "2 of 3 rounds" from "2 of 2 rounds"."""
        record = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings, max_rounds=5).run(make_task())
        assert record.k_rounds == 5
        payload = record.as_dict()
        assert payload["kRounds"] == 5
        assert payload["round_count"] == len(payload["rounds"])

    def test_recording_hash_covers_rounds_and_decision(self, settings: Settings) -> None:
        approve = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings).run(make_task())
        escalate = Orchestrator(make_cohort([-0.8, 0.0, 0.8]), settings).run(make_task(risk=0.9))
        assert canonical_recording_hash(approve) != canonical_recording_hash(escalate)
        assert canonical_recording_hash(approve) == canonical_recording_hash(approve)

    def test_summarise_is_a_single_line(self, settings: Settings) -> None:
        record = Orchestrator(make_cohort([0.0, 0.0, 0.0]), settings).run(make_task())
        line = summarise(record)
        assert "\n" not in line
        assert "Approved" in line
