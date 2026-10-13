"""Deterministic offline validator.

Purpose, stated plainly: this adapter does **not** call any model. It is a *deterministic
fixture* that lets ``scripts/demo``, the test suite and the frontend run end-to-end with no
API keys and no network. Its rehearsals are produced by a seeded, documented procedure, and
every verdict it emits is tagged ``provider="offline-deterministic"`` so the panel and the
ledger can never mistake an offline run for a live multi-model run.

This is how the repository satisfies quality redline 1 ("no fabricated data"): offline output
is real output of a real code path, and it is labelled as offline rather than presented as a
model result. Live cohorts require real provider credentials - see ``cohort.yaml``.

The rehearsal procedure is intentionally simple and fully specified:

* each agent has a fixed ``stance`` in ``[-1, 1]`` and a fixed ``scale``;
* the *effective* stance is ``stance * risk_fraction(task)``, where ``risk_fraction`` comes
  from ``task.payload["risk_fraction"]`` (default ``1.0``). This is what makes the fixture
  usable: the sample tasks declare how ambiguous their own geometry is, so the same three
  stances produce a tight agreement on an easy task and a wide spread on an ambiguous one,
  and the demo can exercise all three decision bands without a credential;
* the action sequence is the requested sequence, optionally perturbed by removing one action
  or substituting one primitive, according to the effective stance;
* the trajectory is a straight line from the origin to ``terminal`` over ``len(actions)+1``
  points, with a deterministic per-step offset proportional to the effective stance;
* ``response`` is ``100 - round(45 * |effective stance|)`` clamped, so a stance near zero
  means a confident "safe" rehearsal and a large stance means a maximal-uncertainty one.

None of this is a model judgement, and none of it is presented as one.
"""

from __future__ import annotations

import hashlib
import time

from .base import BaseValidator, TaskRequest
from divergence.verdict import Verdict

PROVIDER = "offline-deterministic"

#: Fallback risk fraction when a task does not declare one.
DEFAULT_RISK_FRACTION = 1.0


class SimulatedValidator(BaseValidator):
    """A seeded, offline, non-model validation agent."""

    def __init__(
        self,
        *,
        name: str,
        stance: float,
        framework: str = "deterministic-fixture",
        scale: float = 1.0,
        dims: int = 2,
        model: str = "none-offline-fixture",
    ) -> None:
        self.name = name
        self.stance = float(stance)
        self.scale = float(scale)
        self.dims = int(dims)
        self.framework = framework
        self.model = model
        self.provider = PROVIDER
        self.endpoint = "offline://deterministic"

    #: Backwards/forwards compatible alias: earlier revisions called this ``bias``.
    @property
    def bias(self) -> float:
        return self.stance

    def is_available(self) -> bool:
        return True

    def _seed(self, task: TaskRequest) -> int:
        digest = hashlib.sha256(f"{self.name}:{task.task_id}".encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big")

    @staticmethod
    def risk_fraction(task: TaskRequest) -> float:
        """How ambiguous the task declares itself to be, in ``[0, 1]``."""
        raw = task.payload.get("risk_fraction", DEFAULT_RISK_FRACTION)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_RISK_FRACTION
        return min(max(value, 0.0), 1.0)

    def rehearse(self, task: TaskRequest, *, tag: str = "soft") -> Verdict:
        started = time.perf_counter()
        seed = self._seed(task)
        effective = self.stance * self.risk_fraction(task)
        actions = list(task.actions) or ["noop"]

        # --- discrete layer: perturb the plan deterministically -------------------
        magnitude_tier = abs(effective)
        if magnitude_tier > 0.5 and len(actions) > 1:
            actions = actions[:-1]
        elif magnitude_tier > 0.2:
            index = seed % len(actions)
            actions[index] = f"alt_{actions[index]}"

        # --- terminal + trajectory ------------------------------------------------
        magnitude = 2.0 * effective * self.scale
        terminal = [
            round(magnitude * (1.0 + 0.1 * ((seed >> (4 * k)) & 0xF) / 15.0), 6)
            for k in range(self.dims)
        ]
        steps = max(len(actions), 1) + 1
        trajectory: list[list[float]] = []
        for step in range(steps):
            fraction = step / (steps - 1)
            wobble = 0.05 * effective * (1.0 if step % 2 == 0 else -1.0)
            trajectory.append([round(value * fraction + wobble, 6) for value in terminal])

        response = max(0, min(100, 100 - int(round(45 * magnitude_tier))))
        latency_ms = max(1, int((time.perf_counter() - started) * 1000))

        return Verdict(
            agent=self.name,
            model=self.model,
            provider=self.provider,
            response=response,
            actions=actions,
            trajectory=trajectory,
            terminal=terminal,
            rationale=(
                f"offline deterministic rehearsal (stance={self.stance:+.2f}, "
                f"risk_fraction={self.risk_fraction(task):.2f}, effective={effective:+.3f}, "
                f"scale={self.scale:g}, seed={seed}); not a model output"
            ),
            evidence_uri=f"offline://{task.task_id}/{self.name}",
            tag=tag,
            latency_ms=latency_ms,
            error=None,
        )


def unanimous_cohort() -> list[SimulatedValidator]:
    """Three offline agents that agree exactly: D_rel -> 0, expected ``Approved``."""
    return [SimulatedValidator(name=f"offline-unanimous-{i + 1}", stance=0.0) for i in range(3)]


def spread_cohort() -> list[SimulatedValidator]:
    """Three offline agents with fixed opposing stances.

    Their disagreement scales with ``task.payload["risk_fraction"]``, which is how the same
    cohort produces an ``Approved`` reading on an unambiguous task and a ``Rejected`` reading
    on an ambiguous or out-of-scope one.
    """
    return [
        SimulatedValidator(name="offline-hold-a", stance=-0.8, scale=1.0),
        SimulatedValidator(name="offline-abstain-b", stance=0.0, scale=1.0),
        SimulatedValidator(name="offline-push-c", stance=+0.8, scale=1.0),
    ]
