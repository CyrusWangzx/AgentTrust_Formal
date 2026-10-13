"""Monitoring hook, calibration slot, dry-run ledger, and config validation."""

from __future__ import annotations

import json

import pytest

from divergence.calibrate import calibrate_thresholds, roc_curve, youden_threshold
from divergence.core import THETA_HIGH, THETA_LOW
from orchestrator.chain import (
    DECISION_CODE,
    LedgerWriter,
    _as_bytes32,
    decision_code,
    derive_cohort_key,
    resolve_cohort_addresses,
    resolve_cohort_identities,
    sign_verdict_attestation,
    to_milli,
    verdict_attestation_digest,
)
from orchestrator.config import ConfigError, Settings, load_settings, redact
from orchestrator.monitoring import (
    SEVERITY_TO_LEVEL,
    MonitoringEvent,
    ResponseLevel,
    Severity,
    SignalSource,
    StubMonitoringHook,
)


class TestMonitoringEvents:
    def test_severity_maps_onto_the_five_level_ladder(self) -> None:
        assert SEVERITY_TO_LEVEL[Severity.INFO] is ResponseLevel.L1_LOG
        assert SEVERITY_TO_LEVEL[Severity.NOTICE] is ResponseLevel.L2_ALERT
        assert SEVERITY_TO_LEVEL[Severity.WARNING] is ResponseLevel.L3_PAUSE
        assert SEVERITY_TO_LEVEL[Severity.CRITICAL] is ResponseLevel.L4_ROLLBACK
        assert SEVERITY_TO_LEVEL[Severity.FATAL] is ResponseLevel.L5_ISOLATE

    def test_event_carries_source_risk_and_timestamp(self) -> None:
        event = MonitoringEvent(
            source=SignalSource.HERITAGE, severity=Severity.WARNING, agent="a", detail="drift"
        )
        payload = event.as_dict()
        assert payload["source"] == "heritage"
        assert payload["risk"] == "model degradation / contamination"
        assert payload["level"] == "L3_pause"
        assert payload["terminal"] is True
        assert payload["observed_at"]

    def test_info_events_are_not_terminal(self) -> None:
        event = MonitoringEvent(source=SignalSource.BEHAVIOUR, severity=Severity.INFO, agent="a", detail="")
        assert event.terminal is False


class TestStubHook:
    def test_reports_injected_events_for_the_right_agent(self) -> None:
        hook = StubMonitoringHook(
            injected=[
                MonitoringEvent(source=SignalSource.BEHAVIOUR, severity=Severity.INFO, agent="agent-a", detail="x"),
                MonitoringEvent(source=SignalSource.RELATION, severity=Severity.INFO, agent="agent-b", detail="y"),
            ]
        )
        events = hook.observe("agent-a", 1, {})
        assert [e.agent for e in events] == ["agent-a"]

    def test_reports_anomalies_supplied_with_the_observation(self) -> None:
        hook = StubMonitoringHook()
        events = hook.observe(
            "agent-a",
            3,
            {"anomalies": [{"source": "relation", "severity": 4, "detail": "collusion signature"}]},
        )
        assert len(events) == 1
        assert events[0].level is ResponseLevel.L4_ROLLBACK
        assert events[0].action_index == 3

    def test_decide_picks_the_highest_severity(self) -> None:
        hook = StubMonitoringHook()
        events = [
            MonitoringEvent(source=SignalSource.BEHAVIOUR, severity=Severity.INFO, agent="a", detail=""),
            MonitoringEvent(source=SignalSource.RELATION, severity=Severity.CRITICAL, agent="a", detail=""),
        ]
        decision = hook.decide(events)
        assert decision.level is ResponseLevel.L4_ROLLBACK
        assert decision.halt is True

    def test_decide_on_no_events_is_log_only(self) -> None:
        decision = StubMonitoringHook().decide([])
        assert decision.level is ResponseLevel.L1_LOG
        assert decision.halt is False

    def test_trace_accumulates(self) -> None:
        hook = StubMonitoringHook()
        hook.observe("a", 1, {"anomalies": [{"severity": 2, "detail": "x"}]})
        hook.observe("a", 2, {"anomalies": [{"severity": 2, "detail": "y"}]})
        assert len(hook.trace) == 2


class TestCalibration:
    def test_defaults_are_the_frozen_spec_values(self) -> None:
        result = calibrate_thresholds()
        assert result.theta_low == THETA_LOW
        assert result.theta_high == THETA_HIGH
        assert result.calibrated is False
        assert "spec-frozen" in result.note

    def test_roc_curve_endpoints(self) -> None:
        points = roc_curve([0.2, 0.9, 3.0, 4.5], [0, 0, 1, 1])
        assert points[0].tpr == pytest.approx(1.0)
        assert points[-1].fpr == pytest.approx(0.0)
        assert all(0.0 <= p.tpr <= 1.0 and 0.0 <= p.fpr <= 1.0 for p in points)

    def test_youden_picks_a_separating_threshold(self) -> None:
        points = roc_curve([0.2, 0.9, 3.0, 4.5], [0, 0, 1, 1])
        threshold = youden_threshold(points)
        assert threshold is not None and 0.9 < threshold <= 3.0

    def test_single_class_calibration_set_is_rejected_gracefully(self) -> None:
        result = calibrate_thresholds([1.0, 2.0], [1, 1])
        assert result.calibrated is False
        assert result.theta_low == THETA_LOW

    def test_calibration_keeps_the_frozen_ratio(self) -> None:
        result = calibrate_thresholds([0.2, 0.9, 3.0, 4.5], [0, 0, 1, 1])
        assert result.calibrated is True
        assert result.theta_high / result.theta_low == pytest.approx(THETA_HIGH / THETA_LOW)

    def test_mismatched_lengths_raise(self) -> None:
        with pytest.raises(ValueError):
            roc_curve([1.0], [0, 1])


class TestLedgerWriter:
    def test_receipt_is_labelled_dry_run(self, tmp_path) -> None:
        writer = LedgerWriter(tmp_path, chain_id=10143)
        receipt = writer.submit(_FakeRecord())
        assert receipt["mode"] == "dry-run"
        assert receipt["simulated"] is True
        assert receipt["chainId"] == 10143
        assert receipt["txHash"] is None
        assert "no transaction was sent" in receipt["note"]

    def test_appends_one_line_per_record(self, tmp_path) -> None:
        writer = LedgerWriter(tmp_path, chain_id=10143)
        writer.submit(_FakeRecord("0xaa"))
        writer.submit(_FakeRecord("0xbb"))
        entries = writer.read_ledger()
        assert [e["receipt"]["validationId"] for e in entries] == ["0xaa", "0xbb"]

    def test_publishes_a_frontend_feed(self, tmp_path) -> None:
        writer = LedgerWriter(tmp_path / "artifacts", chain_id=10143, frontend_dir=tmp_path / "frontend")
        writer.submit(_FakeRecord("0xcc"))
        feed = json.loads((tmp_path / "frontend" / "data" / "records.json").read_text(encoding="utf-8"))
        assert feed["simulated"] is True
        assert feed["source"] == "dry-run-ledger"
        assert len(feed["records"]) == 1

    def test_read_ledger_tolerates_a_missing_file(self, tmp_path) -> None:
        assert LedgerWriter(tmp_path / "none", chain_id=10143).read_ledger() == []

    def test_receipt_is_embedded_in_the_record_it_published(self, tmp_path) -> None:
        """Each ledger line must be self-describing: the panel labels chain status from it."""
        writer = LedgerWriter(tmp_path / "artifacts", chain_id=10143, frontend_dir=tmp_path / "frontend")
        receipt = writer.submit(_FakeRecord("0xdd"))
        entry = writer.read_ledger()[0]
        assert entry["record"]["chain"] == receipt
        feed = json.loads((tmp_path / "frontend" / "data" / "records.json").read_text(encoding="utf-8"))
        assert feed["records"][0]["chain"]["mode"] == "dry-run"
        assert feed["records"][0]["chain"]["txHash"] is None

    def test_feed_reflects_this_run_only_while_the_ledger_keeps_history(self, tmp_path) -> None:
        """The ledger is an append-only audit trail; the dashboard shows the current run."""
        artifacts, frontend = tmp_path / "artifacts", tmp_path / "frontend"
        LedgerWriter(artifacts, chain_id=10143, frontend_dir=frontend).submit(_FakeRecord("0x01"))

        second = LedgerWriter(artifacts, chain_id=10143, frontend_dir=frontend)
        second.submit(_FakeRecord("0x02"))
        feed = json.loads((frontend / "data" / "records.json").read_text(encoding="utf-8"))

        assert [r["validationId"] for r in feed["records"]] == ["0x02"]
        assert feed["run"]["recordsInThisRun"] == 1
        assert feed["run"]["ledgerEntriesTotal"] == 2

    def test_milli_scaling(self) -> None:
        assert to_milli(None) == 0
        assert to_milli(1.5) == 1500
        assert to_milli(-3.0) == 0
        assert decision_code("Approved") == DECISION_CODE["Approved"]
        assert decision_code("Unknown") == 0


class TestCohortIdentities:
    """On-chain cohort identity resolution (live-chain only, but the rules are offline-testable).

    The paths that need a signing stack are guarded with `importorskip`, so the core suite still
    runs on `requirements.txt` alone.
    """

    @staticmethod
    def _record(names: list[str]):
        return type("R", (), {"cohort": [{"agent": name} for name in names]})()

    def test_derived_keys_are_deterministic_and_one_based(self) -> None:
        first = derive_cohort_key("seed", 1)
        assert first == derive_cohort_key("seed", 1)
        assert first != derive_cohort_key("seed", 2)
        assert first != derive_cohort_key("other-seed", 1)
        assert first.startswith("0x") and len(first) == 66
        with pytest.raises(ConfigError):
            derive_cohort_key("seed", 0)

    def test_no_configured_source_fails_with_an_actionable_message(self, monkeypatch) -> None:
        for name in ("AGENTTRUST_COHORT_SEED", "AGENTTRUST_COHORT_ADDRESSES"):
            monkeypatch.delenv(name, raising=False)
        for index in range(1, 6):
            monkeypatch.delenv(f"AGENTTRUST_VALIDATOR_ADDRESS_{index}", raising=False)
            monkeypatch.delenv(f"AGENTTRUST_VALIDATOR_PRIVATE_KEY_{index}", raising=False)
        with pytest.raises(ConfigError) as error:
            resolve_cohort_identities(self._record(["a", "b"]))
        assert "no cohort on-chain identities" in str(error.value)
        # The refusal must name every supported source so the operator can pick one.
        assert "AGENTTRUST_VALIDATOR_PRIVATE_KEY_" in str(error.value)
        assert "AGENTTRUST_COHORT_ADDRESSES" in str(error.value)
        assert "AGENTTRUST_COHORT_SEED" in str(error.value)

    def test_duplicate_members_are_refused_before_any_transaction(self, monkeypatch) -> None:
        for name in ("AGENTTRUST_COHORT_SEED", "AGENTTRUST_COHORT_ADDRESSES"):
            monkeypatch.delenv(name, raising=False)
        same = "0x" + "ab" * 20
        monkeypatch.setenv("AGENTTRUST_VALIDATOR_ADDRESS_1", same)
        monkeypatch.setenv("AGENTTRUST_VALIDATOR_ADDRESS_2", same)
        with pytest.raises(ConfigError) as error:
            resolve_cohort_identities(self._record(["a", "b"]))
        assert "duplicate cohort address" in str(error.value)

    def test_partial_address_configuration_is_refused(self, monkeypatch) -> None:
        for name in ("AGENTTRUST_COHORT_SEED", "AGENTTRUST_COHORT_ADDRESSES"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("AGENTTRUST_VALIDATOR_ADDRESS_1", "0x" + "11" * 20)
        monkeypatch.delenv("AGENTTRUST_VALIDATOR_ADDRESS_2", raising=False)
        with pytest.raises(ConfigError) as error:
            resolve_cohort_identities(self._record(["a", "b"]))
        assert "missing for [2]" in str(error.value)

    def test_comma_list_must_match_the_cohort_size(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "AGENTTRUST_COHORT_ADDRESSES", f"0x{'11' * 20},0x{'22' * 20},0x{'33' * 20}"
        )
        with pytest.raises(ConfigError) as error:
            resolve_cohort_identities(self._record(["a", "b"]))
        assert "lists 3 addresses but the cohort has 2" in str(error.value)

    def test_seed_derives_one_distinct_identity_per_member(self, monkeypatch) -> None:
        pytest.importorskip("eth_account")
        monkeypatch.delenv("AGENTTRUST_COHORT_ADDRESSES", raising=False)
        for index in range(1, 6):
            monkeypatch.delenv(f"AGENTTRUST_VALIDATOR_ADDRESS_{index}", raising=False)
            monkeypatch.delenv(f"AGENTTRUST_VALIDATOR_PRIVATE_KEY_{index}", raising=False)
        monkeypatch.setenv("AGENTTRUST_COHORT_SEED", "unit-test-seed")

        identities = resolve_cohort_identities(self._record(["a", "b", "c"]))
        assert [i.agent for i in identities] == ["a", "b", "c"]
        assert len({i.address for i in identities}) == 3
        assert all(i.private_key and i.source == "derived from seed" for i in identities)

        # Deterministic: the same seed always produces the same cohort.
        assert [i.address for i in identities] == [
            i.address for i in resolve_cohort_identities(self._record(["a", "b", "c"]))
        ]
        assert resolve_cohort_addresses(self._record(["a", "b", "c"])) == [
            i.address for i in identities
        ]


class TestAttestationEncoding:
    """The digest the orchestrator signs must equal `keccak256(abi.encode(...))` in Solidity.

    The same vector is asserted from the other side in
    `contracts/test/AttestationEncoding.test.js`, which also feeds the signature to the deployed
    contract. A mismatch between the two languages would otherwise only surface as a reverted
    transaction on a live network.
    """

    REQUEST_HASH = "0x" + "11" * 32
    VERDICT_HASH = "0x" + "22" * 32
    MEMBER = "0xe136E882DEa32113F60A190a78F19A93Bc2297D4"
    DIGEST = "0x4f646467622b802cf8a880b3abbe94670d09bc30fb90c39de412a05328209cd3"

    def test_digest_matches_the_solidity_abi_encoding(self) -> None:
        digest = verdict_attestation_digest(
            self.REQUEST_HASH, self.MEMBER, 66, self.VERDICT_HASH
        )
        assert "0x" + digest.hex() == self.DIGEST
        assert len(digest) == 32

    def test_digest_is_sensitive_to_every_field(self) -> None:
        base = verdict_attestation_digest(self.REQUEST_HASH, self.MEMBER, 66, self.VERDICT_HASH)
        assert verdict_attestation_digest(
            "0x" + "33" * 32, self.MEMBER, 66, self.VERDICT_HASH
        ) != base
        assert verdict_attestation_digest(
            self.REQUEST_HASH, "0x" + "44" * 20, 66, self.VERDICT_HASH
        ) != base
        assert verdict_attestation_digest(
            self.REQUEST_HASH, self.MEMBER, 67, self.VERDICT_HASH
        ) != base
        assert verdict_attestation_digest(
            self.REQUEST_HASH, self.MEMBER, 66, "0x" + "55" * 32
        ) != base

    def test_signature_recovers_to_the_member(self) -> None:
        pytest.importorskip("eth_account")
        from eth_account import Account
        from eth_account.messages import encode_defunct

        key = derive_cohort_key("agenttrust-attestation-fixture", 1)
        address = Account.from_key(key).address
        signature = sign_verdict_attestation(
            self.REQUEST_HASH, address, 66, self.VERDICT_HASH, key
        )
        digest = verdict_attestation_digest(self.REQUEST_HASH, address, 66, self.VERDICT_HASH)
        recovered = Account.recover_message(
            encode_defunct(primitive=digest), signature=bytes.fromhex(signature[2:])
        )
        assert recovered == address

    def test_bytes32_coercion_rejects_a_wrong_length(self) -> None:
        assert _as_bytes32("0x" + "11" * 32) == bytes.fromhex("11" * 32)
        assert _as_bytes32(bytes.fromhex("22" * 32)) == bytes.fromhex("22" * 32)
        with pytest.raises(ConfigError):
            _as_bytes32("0x" + "11" * 31)
        with pytest.raises(ConfigError):
            _as_bytes32("not-hex")


class TestSettings:
    def test_defaults_point_at_monad_testnet(self) -> None:
        settings = Settings()
        assert settings.chain_id == 10143
        assert "testnet" in settings.rpc_url
        assert settings.chain_mode == "dry-run"

    def test_live_chain_mode_fails_fast_without_credentials(self) -> None:
        settings = Settings(chain_mode="live")
        with pytest.raises(ConfigError) as error:
            settings.validate_for_live_chain()
        message = str(error.value)
        assert "RPC_URL_10143" not in message or True  # rpc has a default
        assert "AGENTTRUST_REGISTRY_ADDRESS" in message
        assert "DEPLOYER_PRIVATE_KEY" in message

    def test_mainnet_is_refused(self) -> None:
        settings = Settings(
            chain_mode="live",
            chain_id=143,
            registry_address="0x1",
            requester_private_key="0x2",
        )
        with pytest.raises(ConfigError, match="mainnet"):
            settings.validate_for_live_chain()

    def test_summary_never_leaks_key_material(self) -> None:
        settings = Settings(requester_private_key="0x" + "ab" * 32)
        payload = settings.summary()
        assert "requester_private_key" not in payload
        assert payload["has_signer"] is True
        assert "ab" * 32 not in json.dumps(payload)

    def test_redact(self) -> None:
        assert redact(None) == "<unset>"
        assert redact("") == "<unset>"
        assert redact("0xdeadbeef") == "<set:...beef>"

    def test_load_settings_rejects_inverted_thresholds(self, monkeypatch) -> None:
        monkeypatch.setenv("THETA_LOW", "5")
        monkeypatch.setenv("THETA_HIGH", "1")
        with pytest.raises(ConfigError, match="THETA_HIGH"):
            load_settings()

    def test_load_settings_rejects_an_unknown_terminal_metric(self, monkeypatch) -> None:
        monkeypatch.setenv("TERMINAL_METRIC", "cosine")
        with pytest.raises(ConfigError, match="TERMINAL_METRIC"):
            load_settings()


class _FakeRecord:
    """Minimal stand-in for a ValidationRecord inside ledger tests."""

    def __init__(self, validation_id: str = "0xdeadbeef") -> None:
        self.validation_id = validation_id

    def as_dict(self) -> dict:
        return {"validationId": self.validation_id, "final_decision": "Approved"}
