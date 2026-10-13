"""In-execution monitoring hooks (spec 2.2 item 6 / plan section 3.3).

The work order allows this to be an *interface plus stub*, but requires the interface to be
complete. That is exactly what this module is:

* :class:`SignalSource` -- the three detectors (行为层 / 关系层 / 传承层)
* :class:`ResponseLevel` -- the L1..L5 escalation ladder
* :class:`MonitoringEvent` -- one reported anomaly
* :class:`MonitoringHook` -- the interface the execution loop calls
* :class:`StubMonitoringHook` -- a working, side-effect-free implementation used by the demo

The stub implements the *policy* (severity -> level, level -> action) faithfully and detects
nothing on its own: it reports whatever ``observe()`` is given. Replacing it with a real
detector requires no change to the orchestrator, which is the point of freezing the interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Protocol, Sequence


class SignalSource(str, Enum):
    """The three monitoring signal sources."""

    BEHAVIOUR = "behaviour"
    """行为层: authorization overreach - an action outside the granted scope."""

    RELATION = "relation"
    """关系层: collaboration-network anomaly - collusion or coordination failure."""

    HERITAGE = "heritage"
    """传承层: lineage integrity - agent version / skill drift, model contamination."""


class Severity(int, Enum):
    """Anomaly severity, mapped 1:1 onto the response ladder."""

    INFO = 1
    NOTICE = 2
    WARNING = 3
    CRITICAL = 4
    FATAL = 5


class ResponseLevel(str, Enum):
    """The five-level response ladder (L1 日志 -> L5 隔离)."""

    L1_LOG = "L1_log"
    L2_ALERT = "L2_alert"
    L3_PAUSE = "L3_pause"
    L4_ROLLBACK = "L4_rollback"
    L5_ISOLATE = "L5_isolate"


#: Severity -> default response level. ``Severity.CRITICAL`` maps to rollback because the
#: action has already been released by the pre-execution gate and needs undoing.
SEVERITY_TO_LEVEL: dict[Severity, ResponseLevel] = {
    Severity.INFO: ResponseLevel.L1_LOG,
    Severity.NOTICE: ResponseLevel.L2_ALERT,
    Severity.WARNING: ResponseLevel.L3_PAUSE,
    Severity.CRITICAL: ResponseLevel.L4_ROLLBACK,
    Severity.FATAL: ResponseLevel.L5_ISOLATE,
}

#: Whether a response level halts execution of the monitored agent.
TERMINAL_LEVELS: frozenset[ResponseLevel] = frozenset(
    {ResponseLevel.L3_PAUSE, ResponseLevel.L4_ROLLBACK, ResponseLevel.L5_ISOLATE}
)


@dataclass
class MonitoringEvent:
    """One anomaly reported by a monitoring signal source."""

    source: SignalSource
    severity: Severity
    agent: str
    detail: str
    action_index: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    observed_at: str = ""

    def __post_init__(self) -> None:
        if not self.observed_at:
            self.observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    @property
    def level(self) -> ResponseLevel:
        return SEVERITY_TO_LEVEL[self.severity]

    @property
    def terminal(self) -> bool:
        return self.level in TERMINAL_LEVELS

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "risk": {
                SignalSource.BEHAVIOUR: "authorization overreach",
                SignalSource.RELATION: "collaboration failure / collusion",
                SignalSource.HERITAGE: "model degradation / contamination",
            }[self.source],
            "severity": self.severity.name,
            "level": self.level.value,
            "agent": self.agent,
            "action_index": self.action_index,
            "detail": self.detail,
            "evidence": self.evidence,
            "terminal": self.terminal,
            "observed_at": self.observed_at,
        }


@dataclass
class MonitoringDecision:
    """Aggregated monitoring outcome for one execution step."""

    level: ResponseLevel
    halt: bool
    events: list[MonitoringEvent] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "halt": self.halt,
            "events": [e.as_dict() for e in self.events],
        }


class MonitoringHook(Protocol):
    """The interface the execution loop depends on.

    Implementations MUST be side-effect free with respect to the monitored agent: they report,
    they do not act. Acting is the caller's job, driven by the returned
    :class:`MonitoringDecision`.
    """

    def observe(self, agent: str, step: int, observation: dict[str, Any]) -> Sequence[MonitoringEvent]:
        """Inspect one execution step and return any anomalies found."""

    def decide(self, events: Iterable[MonitoringEvent]) -> MonitoringDecision:
        """Fold anomalies into the highest applicable response level."""


class StubMonitoringHook:
    """Working stub: faithful policy, no detection.

    ``observe`` forwards any anomalies the caller injects via ``observed_events`` or the
    ``observation["anomalies"]`` list, so the full ladder can be demonstrated end to end
    without shipping a half-finished detector.
    """

    def __init__(self, injected: Sequence[MonitoringEvent] | None = None) -> None:
        self._injected = list(injected or [])
        self.trace: list[MonitoringEvent] = []

    def observe(self, agent: str, step: int, observation: dict[str, Any]) -> list[MonitoringEvent]:
        events: list[MonitoringEvent] = [
            event for event in self._injected if event.agent in ("", agent)
        ]
        for raw in observation.get("anomalies", []):
            events.append(
                MonitoringEvent(
                    source=SignalSource(raw.get("source", SignalSource.BEHAVIOUR.value)),
                    severity=Severity(int(raw.get("severity", 1))),
                    agent=agent,
                    action_index=raw.get("action_index", step),
                    detail=str(raw.get("detail", "")),
                    evidence=dict(raw.get("evidence") or {}),
                )
            )
        self.trace.extend(events)
        return events

    def decide(self, events: Iterable[MonitoringEvent]) -> MonitoringDecision:
        collected = list(events)
        if not collected:
            return MonitoringDecision(level=ResponseLevel.L1_LOG, halt=False, events=[])
        highest = max(collected, key=lambda e: e.severity)
        return MonitoringDecision(level=highest.level, halt=highest.terminal, events=collected)


def annotation_hook(events: Sequence[MonitoringEvent]) -> StubMonitoringHook:
    """Build a stub hook that reports the given fixed anomalies (used by tests and docs)."""
    return StubMonitoringHook(injected=events)
