"""Heterogeneous validation agents (spec 2.5 / 2.6).

Public surface:

* :class:`BaseValidator` -- the adapter contract, ``rehearse(task) -> Verdict``
* :class:`TaskRequest`   -- the task payload handed to every validator
* :class:`QwenMaxValidator` / :class:`KimiValidator` -- live model adapters
* :class:`SimulatedValidator` -- deterministic offline fixture (never a model result)
* :func:`load_cohort` / :func:`verify_heterogeneity` -- cohort materialisation + triad check
"""

from .base import (
    BaseValidator,
    FRAMEWORK_ADVERSARIAL,
    FRAMEWORK_BREADTH,
    FRAMEWORK_CHECKLIST,
    FRAMEWORK_PLAN_ACT,
    FRAMEWORK_REFLEXION,
    HttpChatAdapter,
    TaskRequest,
    VerdictParseError,
    build_rehearsal_instruction,
    verdict_from_payload,
)
from .cohort import (
    Cohort,
    HeterogeneityReport,
    build_validator,
    describe_cohort,
    load_cohort,
    load_cohort_config,
    verify_heterogeneity,
)
from .kimi import KimiValidator, kimi_auditor, kimi_explorer
from .qwen_max import QwenMaxValidator, qwen_planner, qwen_red_team
from .simulated import PROVIDER as OFFLINE_PROVIDER, SimulatedValidator

__all__ = [
    "BaseValidator",
    "HttpChatAdapter",
    "TaskRequest",
    "VerdictParseError",
    "build_rehearsal_instruction",
    "verdict_from_payload",
    "FRAMEWORK_PLAN_ACT",
    "FRAMEWORK_ADVERSARIAL",
    "FRAMEWORK_CHECKLIST",
    "FRAMEWORK_BREADTH",
    "FRAMEWORK_REFLEXION",
    "QwenMaxValidator",
    "qwen_planner",
    "qwen_red_team",
    "KimiValidator",
    "kimi_auditor",
    "kimi_explorer",
    "SimulatedValidator",
    "OFFLINE_PROVIDER",
    "Cohort",
    "HeterogeneityReport",
    "load_cohort",
    "load_cohort_config",
    "build_validator",
    "verify_heterogeneity",
    "describe_cohort",
]
