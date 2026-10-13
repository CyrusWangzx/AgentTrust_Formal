"""Cohort loading + anti-fake-heterogeneity enforcement (spec 2.5 / 2.6).

``cohort.yaml`` is the declaration; this module is the enforcement. Nothing in the
orchestrator may construct a cohort without passing through :func:`verify_heterogeneity`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import yaml

from .base import BaseValidator, TaskRequest
from .env import env
from .kimi import KimiValidator
from .qwen_max import QwenMaxValidator
from .simulated import SimulatedValidator

COHORT_PATH = Path(__file__).resolve().parent / "cohort.yaml"

#: The three heterogeneity axes. Two members clash when they agree on ALL of them.
AXES = ("model_family", "provider", "framework")


@dataclass(frozen=True)
class HeterogeneityReport:
    """Outcome of the triad check."""

    ok: bool
    strict_ok: bool
    members: int
    model_families: tuple[str, ...]
    providers: tuple[str, ...]
    frameworks: tuple[str, ...]
    clashes: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "strict_ok": self.strict_ok,
            "members": self.members,
            "model_families": list(self.model_families),
            "providers": list(self.providers),
            "frameworks": list(self.frameworks),
            "clashes": list(self.clashes),
            "notes": list(self.notes),
        }


@dataclass
class Cohort:
    """A materialised cohort ready for fan-out."""

    members: list[BaseValidator]
    declarations: list[dict[str, Any]]
    settings: dict[str, Any] = field(default_factory=dict)
    offline: bool = False

    @property
    def names(self) -> list[str]:
        return [m.name for m in self.members]

    @property
    def max_rounds(self) -> int:
        return int(self.settings.get("max_rounds", 3))

    @property
    def min_usable(self) -> int:
        return int(self.settings.get("min_usable", 2))

    def available(self) -> list[BaseValidator]:
        return [m for m in self.members if m.is_available()]

    def rehearse_all(self, task: TaskRequest, *, tag: str = "soft") -> list[Any]:
        """Sequential rehearsal - the orchestrator uses the concurrent path instead."""
        return [m.rehearse(task, tag=tag) for m in self.members]


def load_cohort_config(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else COHORT_PATH
    with target.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"{target} must contain a YAML mapping")
    return config


def _declaration_family(decl: dict[str, Any]) -> str:
    return str(decl.get("model_family", "unknown"))


def verify_heterogeneity(declarations: Sequence[dict[str, Any]]) -> HeterogeneityReport:
    """Check the anti-fake-heterogeneity triad.

    ``ok`` is the enforceable rule: no two members may agree on all three axes, and the
    cohort spans at least two model families. ``strict_ok`` is the stronger reading where
    every model family is distinct - reported honestly rather than assumed.
    """
    clashes: list[str] = []
    for i in range(len(declarations)):
        for j in range(i + 1, len(declarations)):
            a, b = declarations[i], declarations[j]
            same_family = _declaration_family(a) == _declaration_family(b)
            same_provider = a.get("provider") == b.get("provider")
            same_framework = a.get("framework") == b.get("framework")
            if same_family and same_provider and same_framework:
                clashes.append(f"{a.get('name')} == {b.get('name')} on all three axes")

    families = tuple(sorted({_declaration_family(d) for d in declarations}))
    providers = tuple(sorted({str(d.get("provider", "?")) for d in declarations}))
    frameworks = tuple(sorted({str(d.get("framework", "?")) for d in declarations}))

    notes: list[str] = []
    if len(declarations) < 3:
        notes.append(
            f"cohort has {len(declarations)} members; spec 2.2 asks for 3-5 independent rehearsals"
        )
    if len(families) < 2:
        notes.append("cohort spans a single model family: constraint 1 is not met")
    elif len(families) < len(declarations):
        notes.append(
            "two or more members share a model family; endpoints and frameworks still differ. "
            "Enable optional_third_family in cohort.yaml to reach strict mode."
        )

    return HeterogeneityReport(
        ok=not clashes and len(families) >= 2,
        strict_ok=not clashes and len(families) == len(declarations) and len(declarations) >= 3,
        members=len(declarations),
        model_families=families,
        providers=providers,
        frameworks=frameworks,
        clashes=tuple(clashes),
        notes=tuple(notes),
    )


def build_validator(decl: dict[str, Any]) -> BaseValidator:
    """Instantiate one adapter from its declaration."""
    source = str(decl.get("source", ""))
    name = str(decl.get("name", "validator"))
    framework = str(decl.get("framework", "react-plan-then-act"))
    model = env(str(decl["model_env"]), str(decl.get("model_default", ""))) if decl.get("model_env") else None

    if source == "qwen_max":
        provider = str(decl.get("provider", "dashscope-cn"))
        region = "intl" if provider.endswith("intl") else "cn"
        return QwenMaxValidator(name=name, framework=framework, model=model, region=region)
    if source == "kimi":
        provider = str(decl.get("provider", "moonshot-cn"))
        region = "intl" if provider.endswith("intl") else "cn"
        return KimiValidator(name=name, framework=framework, model=model, region=region)
    raise ValueError(f"unknown validator source {source!r} for member {name!r}")


def build_offline_cohort(declarations: Sequence[dict[str, Any]]) -> Cohort:
    members = [
        SimulatedValidator(
            name=str(d.get("name", f"offline-{i}")),
            stance=float(d.get("stance", 0.0)),
            scale=float(d.get("scale", 1.0)),
        )
        for i, d in enumerate(declarations)
    ]
    return Cohort(
        members=members,
        declarations=[dict(d) | {"framework": "deterministic-fixture", "provider": "offline"} for d in declarations],
        settings={"max_rounds": 3, "min_usable": 2},
        offline=True,
    )


def load_cohort(
    mode: str | None = None,
    path: str | Path | None = None,
) -> Cohort:
    """Materialise the cohort for ``mode`` (``live`` | ``offline`` | ``auto``)."""
    config = load_cohort_config(path)
    settings = dict(config.get("settings") or {})
    selected = (mode or str(settings.get("cohort", "auto"))).lower()

    if selected == "offline":
        return build_offline_cohort(list(config.get("offline_members") or []))

    live_decls = list(config.get("live_members") or [])
    optional = config.get("optional_third_family") or {}
    if optional.get("enabled"):
        live_decls.append({k: v for k, v in optional.items() if k != "enabled"})

    members = [build_validator(d) for d in live_decls]
    available = [m for m in members if m.is_available()]
    min_usable = int(settings.get("min_usable", 2))

    if selected == "live":
        return Cohort(members=members, declarations=live_decls, settings=settings, offline=False)

    # `auto`
    if len(available) >= min_usable:
        return Cohort(members=members, declarations=live_decls, settings=settings, offline=False)
    fallback = build_offline_cohort(list(config.get("offline_members") or []))
    fallback.settings.update(settings)
    return fallback


def describe_cohort(cohort: Cohort) -> dict[str, Any]:
    """JSON-ready description of a cohort, including its heterogeneity verdict.

    For offline cohorts the triad is reported as *not applicable* rather than failed: the
    offline members are one deterministic fixture repeated, which is by design. The declared
    **live** cohort's verdict is included alongside so the panel always shows the real
    heterogeneity status of the configuration that will run once credentials exist.
    """
    offline = cohort.offline
    report = verify_heterogeneity(cohort.declarations)
    payload: dict[str, Any] = {
        "offline": offline,
        "member_count": len(cohort.members),
        "available": [m.name for m in cohort.available()],
        "max_rounds": cohort.max_rounds,
        "min_usable": cohort.min_usable,
        "members": [m.identity for m in cohort.members],
        "heterogeneity": {
            "applicable": not offline,
            **report.as_dict(),
            **(
                {
                    "reason": "offline deterministic fixture - the triad applies to live "
                    "model cohorts; see live_heterogeneity"
                }
                if offline
                else {}
            ),
        },
    }
    if offline:
        live_decls = list(load_cohort_config().get("live_members") or [])
        payload["live_heterogeneity"] = verify_heterogeneity(live_decls).as_dict()
    return payload
