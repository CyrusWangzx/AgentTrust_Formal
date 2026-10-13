"""The rehearsal verdict contract shared by validators, orchestrator and on-chain layer.

A validation agent rehearses a task and returns a :class:`Verdict`. It carries the three
signals the divergence metrics consume:

* ``actions``   -- the discrete action sequence  -> ``D_disc``
* ``trajectory``-- the continuous trajectory     -> ``D_traj``
* ``terminal``  -- the final state vector        -> ``D_end``

plus the ERC-8004 response score (0-100) and free-form rationale. The same structure is
hashed to ``verdictHash`` and committed on-chain, so it is deliberately JSON-round-trippable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: JSON schema tag written into every verdict payload.
VERDICT_SCHEMA = "agenttrust.verdict/v1"


@dataclass
class Verdict:
    """Structured output of a single validation agent's rehearsal."""

    agent: str
    """Stable identifier of the validation agent (matches ``cohort.yaml``)."""

    model: str = ""
    """Underlying model of the agent, e.g. ``qwen3.8-max``."""

    provider: str = ""
    """Inference provider / endpoint family, e.g. ``dashscope``."""

    response: int = 0
    """ERC-8004 validation response in ``[0, 100]``."""

    actions: list[str] = field(default_factory=list)
    """Discrete action sequence, e.g. ``["lock()", "retract_arm()", "move_to(x,y)"]``."""

    trajectory: list[list[float]] = field(default_factory=list)
    """Continuous trajectory: a list of vectors (``[[x, y], ...]``)."""

    terminal: list[float] | None = None
    """Terminal state vector; ``None`` marks an abstaining / failed rehearsal."""

    rationale: str = ""
    """Human-readable justification, surfaced in the panel and the demo log."""

    evidence_uri: str = ""
    """Optional pointer to off-chain evidence (ERC-8004 ``responseURI``)."""

    tag: str = "soft"
    """ERC-8004 ``tag``; AgentTrust uses ``soft`` for round 1 and ``hard`` after K rounds."""

    latency_ms: int = 0
    """Wall-clock rehearsal time, recorded for the demo's log stream."""

    error: str | None = None
    """Set when the adapter could not produce a rehearsal (skipped agent)."""

    def __post_init__(self) -> None:
        if not 0 <= int(self.response) <= 100:
            raise ValueError(f"response must be within [0, 100], got {self.response!r}")

    @property
    def usable(self) -> bool:
        """A verdict counts towards divergence only if the rehearsal actually ran."""
        return self.error is None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": VERDICT_SCHEMA,
            "agent": self.agent,
            "model": self.model,
            "provider": self.provider,
            "response": int(self.response),
            "actions": list(self.actions),
            "trajectory": [list(map(float, row)) for row in self.trajectory],
            "terminal": None if self.terminal is None else list(map(float, self.terminal)),
            "rationale": self.rationale,
            "evidenceURI": self.evidence_uri,
            "tag": self.tag,
            "latency_ms": int(self.latency_ms),
            "error": self.error,
        }

    def canonical_json(self) -> str:
        """Deterministic JSON used for hashing (sorted keys, no whitespace drift)."""
        return json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))

    def verdict_hash(self) -> str:
        """``0x``-prefixed keccak-style commitment to the canonical payload.

        Uses SHA-256 over the canonical JSON: the off-chain library stays dependency-free
        while the on-chain layer accepts any 32-byte commitment. See
        ``orchestrator/chain.py`` for the keccak variant used when writing to the registry.
        """
        return "0x" + hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "Verdict":
        return cls(
            agent=str(payload["agent"]),
            model=str(payload.get("model", "")),
            provider=str(payload.get("provider", "")),
            response=int(payload.get("response", 0)),
            actions=list(payload.get("actions") or []),
            trajectory=[list(map(float, row)) for row in (payload.get("trajectory") or [])],
            terminal=(
                None
                if payload.get("terminal") is None
                else list(map(float, payload["terminal"]))
            ),
            rationale=str(payload.get("rationale", "")),
            evidence_uri=str(payload.get("evidenceURI", "")),
            tag=str(payload.get("tag", "soft")),
            latency_ms=int(payload.get("latency_ms", 0)),
            error=payload.get("error"),
        )


def usable_verdicts(verdicts: Sequence[Verdict]) -> list[Verdict]:
    """Filter a cohort down to the verdicts that produced a real rehearsal."""
    return [v for v in verdicts if v.usable]
