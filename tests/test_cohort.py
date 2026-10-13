"""Cohort loading, heterogeneity enforcement, and adapter behaviour (spec 2.5 / 2.6)."""

from __future__ import annotations

import pytest

from divergence.verdict import Verdict
from validators import (
    FRAMEWORK_ADVERSARIAL,
    FRAMEWORK_CHECKLIST,
    FRAMEWORK_PLAN_ACT,
    KimiValidator,
    QwenMaxValidator,
    SimulatedValidator,
    TaskRequest,
    build_rehearsal_instruction,
    describe_cohort,
    load_cohort,
    load_cohort_config,
    verdict_from_payload,
    verify_heterogeneity,
)
from validators.base import VerdictParseError, extract_json_object
from validators.simulated import PROVIDER as OFFLINE_PROVIDER


class TestCohortConfig:
    def test_the_declared_live_cohort_loads(self) -> None:
        config = load_cohort_config()
        assert config["settings"]["max_rounds"] == 3
        assert config["settings"]["min_usable"] == 2
        assert len(config["live_members"]) == 5

    def test_live_cohort_mode_builds_live_adapters(self) -> None:
        cohort = load_cohort("live")
        assert cohort.offline is False
        assert len(cohort.members) == 5
        assert {type(m).__name__ for m in cohort.members} == {"QwenMaxValidator", "KimiValidator"}

    def test_offline_cohort_mode_builds_fixtures(self) -> None:
        cohort = load_cohort("offline")
        assert cohort.offline is True
        assert all(isinstance(m, SimulatedValidator) for m in cohort.members)
        assert all(m.is_available() for m in cohort.members)

    def test_auto_falls_back_to_offline_without_credentials(self, monkeypatch) -> None:
        for name in ("DASHSCOPE_API_KEY", "MOONSHOT_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        cohort = load_cohort("auto")
        assert cohort.offline is True  # fewer than min_usable live members available

    def test_auto_uses_the_live_cohort_once_a_credential_exists(self, monkeypatch) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
        monkeypatch.setenv("MOONSHOT_API_KEY", "sk-test")
        cohort = load_cohort("auto")
        assert cohort.offline is False
        assert len(cohort.available()) == 5

    def test_describe_cohort_reports_live_heterogeneity_for_offline_runs(self) -> None:
        payload = describe_cohort(load_cohort("offline"))
        assert payload["heterogeneity"]["applicable"] is False
        assert payload["live_heterogeneity"]["ok"] is True

    def test_unknown_source_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown validator source"):
            from validators.cohort import build_validator

            build_validator({"name": "x", "source": "not-a-provider"})


class TestHeterogeneity:
    def _member(self, name: str, family: str, provider: str, framework: str) -> dict:
        return {"name": name, "model_family": family, "provider": provider, "framework": framework}

    def test_declared_cohort_satisfies_the_triad(self) -> None:
        report = verify_heterogeneity(load_cohort_config()["live_members"])
        assert report.ok is True
        assert report.clashes == ()
        assert set(report.model_families) == {"qwen", "kimi"}
        assert len(report.providers) == 4
        assert len(report.frameworks) == 5

    def test_strict_mode_is_honestly_reported_as_false(self) -> None:
        report = verify_heterogeneity(load_cohort_config()["live_members"])
        assert report.strict_ok is False
        assert any("optional_third_family" in note for note in report.notes)

    def test_clash_on_all_three_axes_is_rejected(self) -> None:
        report = verify_heterogeneity(
            [
                self._member("a", "qwen", "dashscope-cn", FRAMEWORK_PLAN_ACT),
                self._member("b", "qwen", "dashscope-cn", FRAMEWORK_PLAN_ACT),
            ]
        )
        assert report.ok is False
        assert len(report.clashes) == 1

    def test_same_family_pairing_is_clash_free_but_still_fails_the_family_span_rule(self) -> None:
        """Both halves of the triad matter: distinct axes, and at least two model families."""
        report = verify_heterogeneity(
            [
                self._member("a", "qwen", "dashscope-cn", FRAMEWORK_PLAN_ACT),
                self._member("b", "qwen", "dashscope-intl", FRAMEWORK_ADVERSARIAL),
            ]
        )
        assert report.clashes == ()          # no member duplicates another on all three axes
        assert report.ok is False            # but constraint 1 (different sources) is unmet
        assert any("single model family" in note for note in report.notes)

    def test_strict_mode_true_when_every_family_is_distinct(self) -> None:
        report = verify_heterogeneity(
            [
                self._member("a", "qwen", "dashscope-cn", FRAMEWORK_PLAN_ACT),
                self._member("b", "kimi", "moonshot-cn", FRAMEWORK_CHECKLIST),
                self._member("c", "third", "third-cn", FRAMEWORK_ADVERSARIAL),
            ]
        )
        assert report.ok is True and report.strict_ok is True

    def test_single_family_is_not_ok(self) -> None:
        report = verify_heterogeneity(
            [self._member("a", "qwen", "dashscope-cn", FRAMEWORK_PLAN_ACT)]
        )
        assert report.ok is False
        assert any("single model family" in note for note in report.notes)


class TestAdapters:
    def test_qwen_adapter_is_unavailable_without_a_key(self) -> None:
        adapter = QwenMaxValidator(api_key="")
        assert adapter.is_available() is False
        verdict = adapter.rehearse(TaskRequest(task_id="t", description="d"))
        assert verdict.usable is False
        assert "API key not configured" in (verdict.error or "")
        assert verdict.agent == "qwen-planner"

    def test_kimi_adapter_is_unavailable_without_a_key(self) -> None:
        adapter = KimiValidator(api_key="")
        assert adapter.is_available() is False
        assert adapter.rehearse(TaskRequest(task_id="t", description="d")).usable is False

    def test_adapters_never_raise_on_a_bad_endpoint(self) -> None:
        adapter = QwenMaxValidator(api_key="sk-fake", base_url="http://127.0.0.1:9/v1")
        verdict = adapter.rehearse(TaskRequest(task_id="t", description="d"))
        assert verdict.error is not None  # reported, not raised (spec 2.6)

    def test_frameworks_produce_distinct_instructions(self) -> None:
        texts = {f: build_rehearsal_instruction(f) for f in (FRAMEWORK_PLAN_ACT, FRAMEWORK_ADVERSARIAL, FRAMEWORK_CHECKLIST)}
        assert len(set(texts.values())) == 3
        for text in texts.values():
            assert "JSON" in text
            assert "actions" in text and "trajectory" in text and "terminal" in text


class TestVerdictParsing:
    def test_extracts_a_bare_json_object(self) -> None:
        assert extract_json_object('{"a": 1}') == {"a": 1}

    def test_extracts_from_a_fenced_block(self) -> None:
        assert extract_json_object('here you go:\n```json\n{"a": 1}\n```\nthanks') == {"a": 1}

    def test_extracts_surrounded_by_prose(self) -> None:
        assert extract_json_object('Certainly. {"a": {"b": 2}} done') == {"a": {"b": 2}}

    def test_raises_on_garbage(self) -> None:
        with pytest.raises(VerdictParseError):
            extract_json_object("no json here")
        with pytest.raises(VerdictParseError):
            extract_json_object("")

    def test_coerces_a_full_payload(self) -> None:
        verdict = verdict_from_payload(
            {
                "actions": ["move", "grip"],
                "trajectory": [[0.0, 0.0], [1.0, 2.0]],
                "terminal": [1.0, 2.0],
                "response": 88,
                "rationale": "looks fine",
            },
            agent="a",
            model="m",
            provider="p",
            framework="f",
        )
        assert isinstance(verdict, Verdict)
        assert verdict.response == 88
        assert verdict.actions == ["move", "grip"]
        assert verdict.terminal == [1.0, 2.0]

    def test_clamps_and_defaults_a_sloppy_payload(self) -> None:
        verdict = verdict_from_payload(
            {"response": 250}, agent="a", model="m", provider="p", framework="f",
            requested_actions=["keep", "me"],
        )
        assert verdict.response == 100
        assert verdict.actions == ["keep", "me"]
        assert verdict.trajectory == []

    def test_accepts_score_as_an_alias_for_response(self) -> None:
        verdict = verdict_from_payload(
            {"score": 42}, agent="a", model="m", provider="p", framework="f"
        )
        assert verdict.response == 42

    def test_numeric_terminal_is_promoted_to_a_vector(self) -> None:
        verdict = verdict_from_payload(
            {"terminal": 3.5, "trajectory": [0.0, 1.0]},
            agent="a", model="m", provider="p", framework="f",
        )
        assert verdict.terminal == [3.5]


class TestSimulatedFixture:
    def test_verdicts_are_labels_as_offline(self) -> None:
        verdict = SimulatedValidator(name="x", stance=0.0).rehearse(
            TaskRequest(task_id="t", description="d")
        )
        assert verdict.provider == OFFLINE_PROVIDER
        assert "not a model output" in verdict.rationale

    def test_is_deterministic(self) -> None:
        agent = SimulatedValidator(name="x", stance=0.4)
        task = TaskRequest(task_id="t", description="d", actions=["a", "b"])
        first, second = agent.rehearse(task), agent.rehearse(task)
        assert first.actions == second.actions
        assert first.terminal == second.terminal
        assert first.trajectory == second.trajectory

    def test_risk_fraction_controls_the_spread(self) -> None:
        agent = SimulatedValidator(name="x", stance=0.8)
        low = agent.rehearse(TaskRequest(task_id="t", description="d", payload={"risk_fraction": 0.1}))
        high = agent.rehearse(TaskRequest(task_id="t", description="d", payload={"risk_fraction": 1.0}))
        assert abs(high.terminal[0]) > abs(low.terminal[0])
        assert high.response < low.response

    def test_risk_fraction_is_clamped(self) -> None:
        assert SimulatedValidator.risk_fraction(
            TaskRequest(task_id="t", description="d", payload={"risk_fraction": 5})
        ) == 1.0
        assert SimulatedValidator.risk_fraction(
            TaskRequest(task_id="t", description="d", payload={"risk_fraction": -1})
        ) == 0.0
        assert SimulatedValidator.risk_fraction(
            TaskRequest(task_id="t", description="d", payload={"risk_fraction": "nonsense"})
        ) == 1.0

    def test_zero_stance_is_a_confident_safe_rehearsal(self) -> None:
        verdict = SimulatedValidator(name="x", stance=0.0).rehearse(
            TaskRequest(task_id="t", description="d")
        )
        assert verdict.response == 100
        assert verdict.terminal == [0.0, 0.0]
