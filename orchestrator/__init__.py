"""AgentTrust orchestration layer.

* :class:`Orchestrator` -- fan-out, verdict collection, threshold branching, K-round escalation
* :class:`RoundStateMachine` -- the pure K-round escalation state machine
* :class:`Settings` / :func:`load_settings` -- environment-driven configuration
* :class:`LedgerWriter` / :class:`RegistryClient` -- dry-run ledger and live Monad Testnet writer
* :class:`MonitoringHook` -- in-execution monitoring interface (spec 2.2 item 6)
"""

from .chain import (
    DECISION_CODE,
    CohortIdentity,
    LedgerWriter,
    RegistryClient,
    check_registry_deployed,
    decision_code,
    derive_cohort_key,
    make_chain_writer,
    resolve_cohort_addresses,
    resolve_cohort_identities,
    rpc_call,
    sign_verdict_attestation,
    to_milli,
    verdict_attestation_digest,
)
from .config import (
    MONAD_MAINNET_CHAIN_ID,
    MONAD_TESTNET_CHAIN_ID,
    ConfigError,
    Settings,
    load_settings,
)
from .hashing import keccak256, keccak256_hex, request_hash, request_payload
from .models import RoundOutcome, ValidationRecord
from .monitoring import (
    MonitoringDecision,
    MonitoringEvent,
    MonitoringHook,
    ResponseLevel,
    Severity,
    SignalSource,
    StubMonitoringHook,
)
from .orchestrator import (
    Orchestrator,
    canonical_recording_hash,
    make_validation_id,
    summarise,
    usable_count,
)
from .state_machine import MachineAction, MachineState, RoundStateMachine, advance

__all__ = [
    "Orchestrator",
    "RoundStateMachine",
    "MachineState",
    "MachineAction",
    "advance",
    "RoundOutcome",
    "ValidationRecord",
    "Settings",
    "load_settings",
    "ConfigError",
    "MONAD_TESTNET_CHAIN_ID",
    "MONAD_MAINNET_CHAIN_ID",
    "LedgerWriter",
    "RegistryClient",
    "CohortIdentity",
    "resolve_cohort_identities",
    "resolve_cohort_addresses",
    "derive_cohort_key",
    "verdict_attestation_digest",
    "sign_verdict_attestation",
    "make_chain_writer",
    "check_registry_deployed",
    "rpc_call",
    "decision_code",
    "to_milli",
    "DECISION_CODE",
    "keccak256",
    "keccak256_hex",
    "request_hash",
    "request_payload",
    "canonical_recording_hash",
    "make_validation_id",
    "summarise",
    "usable_count",
    "MonitoringHook",
    "MonitoringEvent",
    "MonitoringDecision",
    "SignalSource",
    "Severity",
    "ResponseLevel",
    "StubMonitoringHook",
]
