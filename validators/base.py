"""Validator adapter contract.

Every validation agent implements :meth:`BaseValidator.rehearse` and returns a
:class:`divergence.verdict.Verdict`. Adapters for different model sources are deliberately
thin: they own only *how to reach a model*, never *how to score it*. All scoring happens in
``divergence``, which keeps the divergence readings provably independent of any provider.

Failure policy (spec 2.6): a missing credential or an unreachable endpoint never raises out
of an adapter. The adapter returns a ``Verdict`` with ``error`` set, the orchestrator counts
it as unusable, and the cohort either continues or reports ``INSUFFICIENT_VALIDATORS``.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from divergence.verdict import Verdict

#: Prompt frameworks. Constraint 3 of the anti-fake-heterogeneity triad (spec 2.5) requires
#: cohort members to run *different* reasoning frameworks, not just different weights.
FRAMEWORK_PLAN_ACT = "react-plan-then-act"
FRAMEWORK_ADVERSARIAL = "adversarial-red-team"
FRAMEWORK_CHECKLIST = "checklist-audit"
FRAMEWORK_BREADTH = "breadth-first-exploration"
FRAMEWORK_REFLEXION = "reflexion-self-critique"


@dataclass
class TaskRequest:
    """A task submitted for pre-execution verification."""

    task_id: str
    description: str
    actions: list[str] = field(default_factory=list)
    """The action sequence the main agent intends to execute."""

    constraints: list[str] = field(default_factory=list)
    observation_space: dict[str, Any] = field(default_factory=dict)
    """Hints for the trajectory shape, e.g. ``{"dims": 2, "units": ["m", "m"]}``."""

    d_base: float | None = None
    """Baseline difficulty for this task type (spec 2.3). ``None`` -> INSUFFICIENT_BASELINE."""

    max_steps: int = 8
    payload: dict[str, Any] = field(default_factory=dict)
    """Task-specific extras forwarded verbatim to each validator."""

    def to_prompt(self) -> str:
        return json.dumps(
            {
                "task_id": self.task_id,
                "description": self.description,
                "proposed_actions": self.actions,
                "constraints": self.constraints,
                "observation_space": self.observation_space,
                "max_steps": self.max_steps,
                "payload": self.payload,
            },
            indent=2,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "TaskRequest":
        return cls(
            task_id=str(payload["task_id"]),
            description=str(payload.get("description", "")),
            actions=list(payload.get("proposed_actions") or payload.get("actions") or []),
            constraints=list(payload.get("constraints") or []),
            observation_space=dict(payload.get("observation_space") or {}),
            d_base=payload.get("d_base"),
            max_steps=int(payload.get("max_steps", 8)),
            payload=dict(payload.get("payload") or {}),
        )

    def derive_round(self, round_index: int) -> "TaskRequest":
        """Return the task as it is re-issued for round ``round_index`` (1-based).

        Round 1 is the task itself. Later rounds are the spec's "追问" (follow-up) rounds: the
        original task plus an explicit instruction to reconcile the disagreement, and a
        round-tagged ``task_id`` so that deterministic offline fixtures are seeded afresh
        rather than replaying their previous answer verbatim.
        """
        if round_index <= 1:
            return self
        follow_up = (
            "ROUND {n} FOLLOW-UP. Earlier independent rehearsals disagreed. Re-derive your "
            "answer from first principles, state your assumptions explicitly, and report the "
            "execution you would defend if it were audited. Do not attempt to guess what other "
            "validators concluded."
        ).format(n=round_index)
        return TaskRequest(
            task_id=f"{self.task_id}#r{round_index}",
            description=f"{self.description}\n\n{follow_up}",
            actions=list(self.actions),
            constraints=list(self.constraints),
            observation_space=dict(self.observation_space),
            d_base=self.d_base,
            max_steps=self.max_steps,
            payload=dict(self.payload) | {"round": round_index, "follow_up": follow_up},
        )


class VerdictParseError(ValueError):
    """Raised when a model response cannot be coerced into a Verdict."""


#: The JSON contract every adapter asks the model to satisfy.
VERDICT_JSON_SCHEMA: dict[str, Any] = {
    "actions": ["<canonical action 1>", "<canonical action 2>"],
    "trajectory": [[0.0, 0.0], [0.1, 0.2]],
    "terminal": [0.0, 0.0],
    "response": 90,
    "rationale": "<one to three sentences>",
}


def build_rehearsal_instruction(framework: str) -> str:
    """Framework-specific system prompt.

    Each framework asks a *structurally different* question so that a shared blind spot
    (common-cause failure) is less likely to survive all of them.
    """
    schema = json.dumps(VERDICT_JSON_SCHEMA, indent=2)
    shared = (
        "You are one of several independent validation agents. You rehearse a proposed "
        "action sequence BEFORE it is executed and predict what will happen. You must not "
        "assume what other validators concluded - you have no access to them.\n\n"
        "Reply with a single JSON object and nothing else, matching this schema:\n"
        f"{schema}\n\n"
        "Field rules:\n"
        "- actions: the canonical action sequence YOU would execute, as an array of short strings.\n"
        "- trajectory: the predicted continuous trajectory as an array of numeric vectors "
        "(use the observation_space dimensionality).\n"
        "- terminal: the final state vector, same dimensionality as one trajectory point.\n"
        "- response: your confidence that this plan is safe to execute, an integer 0-100 "
        "(100 = safe to execute, 0 = must not execute).\n"
        "- rationale: why, in one to three sentences.\n"
    )
    frameworks = {
        FRAMEWORK_PLAN_ACT: (
            "Reasoning framework: PLAN-THEN-ACT. First derive an ordered plan of primitive "
            "actions that satisfies every constraint, then simulate it forward step by step "
            "to obtain the trajectory and terminal state."
        ),
        FRAMEWORK_ADVERSARIAL: (
            "Reasoning framework: ADVERSARIAL RED-TEAM. Actively search for the most likely "
            "way this plan fails or violates a constraint, and report the trajectory you "
            "believe will actually occur if the plan is executed unmodified."
        ),
        FRAMEWORK_CHECKLIST: (
            "Reasoning framework: CHECKLIST AUDIT. Evaluate each stated constraint "
            "independently as pass/fail, then emit the action sequence that the checklisted "
            "plan implies and the state it ends in."
        ),
        FRAMEWORK_BREADTH: (
            "Reasoning framework: BREADTH-FIRST EXPLORATION. Enumerate several plausible "
            "executions, keep the one with the largest feasible margin to every constraint "
            "boundary, and report that execution."
        ),
        FRAMEWORK_REFLEXION: (
            "Reasoning framework: REFLEXION. Draft an execution, critique your own draft for "
            "hidden assumptions, then report the corrected execution."
        ),
    }
    return shared + "\n" + frameworks.get(framework, "")


def extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model response.

    Models wrap JSON in prose or ```json fences often enough that the adapters need a
    tolerant extractor. Raises :class:`VerdictParseError` when nothing parses.
    """
    if not text or not text.strip():
        raise VerdictParseError("empty model response")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    if start != -1:
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise VerdictParseError(f"no JSON object found in model response: {text[:200]!r}")


def coerce_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def coerce_vector(value: Any, dims: int | None) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return None
    out: list[float] = []
    for item in value:
        number = coerce_number(item)
        if number is None:
            return None
        out.append(number)
    if dims is not None and len(out) != dims:
        return None
    return out


def coerce_trajectory(value: Any, dims: int | None) -> list[list[float]]:
    if not isinstance(value, (list, tuple)):
        return []
    rows: list[list[float]] = []
    for row in value:
        vector = coerce_vector(row, dims)
        if vector is not None:
            rows.append(vector)
    return rows


def verdict_from_payload(
    payload: Mapping[str, Any],
    *,
    agent: str,
    model: str,
    provider: str,
    framework: str,
    latency_ms: int = 0,
    evidence_uri: str = "",
    tag: str = "soft",
    requested_actions: Sequence[str] | None = None,
) -> Verdict:
    """Normalise a raw model payload into a Verdict.

    A model is allowed to answer with a confidence score only; in that case the proposed
    action sequence is echoed so the discrete layer still has a signal, and the reading is
    marked as degraded by the adapter's ``rationale``.
    """
    dims_raw = payload.get("trajectory") or []
    inferred_dims: int | None = None
    if isinstance(dims_raw, (list, tuple)) and dims_raw:
        first = dims_raw[0]
        if isinstance(first, (list, tuple)):
            inferred_dims = len(first)
        elif isinstance(first, (int, float)):
            inferred_dims = 1

    trajectory = coerce_trajectory(payload.get("trajectory"), inferred_dims)
    terminal = coerce_vector(payload.get("terminal"), inferred_dims)

    raw_actions = payload.get("actions")
    actions = [str(a) for a in raw_actions] if isinstance(raw_actions, (list, tuple)) else []
    if not actions and requested_actions is not None:
        actions = list(requested_actions)

    response = coerce_number(payload.get("response"))
    if response is None:
        response = coerce_number(payload.get("score"))
    if response is None:
        response = 50.0
    response_int = int(max(0.0, min(100.0, round(response))))

    return Verdict(
        agent=agent,
        model=model,
        provider=provider,
        response=response_int,
        actions=actions,
        trajectory=trajectory,
        terminal=terminal,
        rationale=str(payload.get("rationale", ""))[:2000],
        evidence_uri=evidence_uri,
        tag=tag,
        latency_ms=latency_ms,
        error=None,
    )


class BaseValidator(ABC):
    """Base class for every validation agent adapter."""

    #: Stable identifier used in ``cohort.yaml`` and in the on-chain verdict record.
    name: str = "base"
    #: Underlying model id.
    model: str = ""
    #: Inference provider / endpoint family.
    provider: str = ""
    #: Reasoning framework (see the ``FRAMEWORK_*`` constants).
    framework: str = ""
    #: Concrete endpoint currently configured.
    endpoint: str = ""

    @abstractmethod
    def rehearse(self, task: TaskRequest, *, tag: str = "soft") -> Verdict:
        """Independently rehearse ``task`` and return a Verdict."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this agent can run right now (credentials present, endpoint reachable)."""

    @property
    def identity(self) -> dict[str, str]:
        return {
            "agent": self.name,
            "model": self.model,
            "provider": self.provider,
            "framework": self.framework,
            "endpoint": self.endpoint,
        }

    def unavailable_verdict(self, reason: str, task: TaskRequest, tag: str = "soft") -> Verdict:
        return Verdict(
            agent=self.name,
            model=self.model,
            provider=self.provider,
            response=0,
            actions=list(task.actions),
            trajectory=[],
            terminal=None,
            rationale="",
            tag=tag,
            error=reason,
        )


class HttpChatAdapter(BaseValidator):
    """Shared OpenAI-compatible ``/chat/completions`` transport.

    Uses only the standard library so the repository stays dependency-free for the demo and
    test suites. Adapters supply the base URL, model id and API key.
    """

    #: Path appended to :attr:`base_url`.
    chat_path = "/chat/completions"
    timeout_seconds = 90.0
    max_tokens = 2048
    temperature = 0.7

    def __init__(
        self,
        *,
        name: str,
        model: str,
        provider: str,
        framework: str,
        base_url: str,
        api_key: str | None = None,
        temperature: float | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.provider = provider
        self.framework = framework
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}{self.chat_path}"
        self._api_key = api_key
        if temperature is not None:
            self.temperature = temperature

    def is_available(self) -> bool:
        return bool(self._api_key)

    def rehearse(self, task: TaskRequest, *, tag: str = "soft") -> Verdict:
        if not self._api_key:
            return self.unavailable_verdict(
                f"{self.provider} API key not configured; agent skipped", task, tag
            )
        started = time.perf_counter()
        try:
            body = self._post(task)
        except Exception as exc:  # noqa: BLE001 - adapters must never raise (spec 2.6)
            return self.unavailable_verdict(f"{type(exc).__name__}: {exc}", task, tag)
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            payload = extract_json_object(body)
            return verdict_from_payload(
                payload,
                agent=self.name,
                model=self.model,
                provider=self.provider,
                framework=self.framework,
                latency_ms=latency_ms,
                tag=tag,
                requested_actions=task.actions,
            )
        except VerdictParseError as exc:
            return self.unavailable_verdict(f"unparseable verdict: {exc}", task, tag)

    def _post(self, task: TaskRequest) -> str:
        import urllib.error
        import urllib.request

        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": build_rehearsal_instruction(self.framework)},
                {
                    "role": "user",
                    "content": "Rehearse this task and reply with the JSON object only:\n\n"
                    + task.to_prompt(),
                },
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"HTTP {exc.code} from {self.provider}: {detail}") from exc
        parsed = json.loads(raw)
        choices = parsed.get("choices") or []
        if not choices:
            raise RuntimeError(f"no choices in {self.provider} response: {raw[:200]}")
        return str(choices[0].get("message", {}).get("content", ""))
