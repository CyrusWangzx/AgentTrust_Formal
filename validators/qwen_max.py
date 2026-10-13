"""Qwen adapter (Alibaba Cloud Model Studio / DashScope, OpenAI-compatible mode).

The Monad Metropolis bounty names the model "Qwen 3.8 Max". DashScope exposes the
OpenAI-compatible surface under ``/compatible-mode/v1`` and the served model id is
configuration, not a constant: it is read from ``QWEN_MODEL`` (``cohort.yaml`` declares the
expected value) so the repository never hard-codes an id that could differ from the account's
actual entitlement. If the id is wrong, DashScope answers with a 400 naming the valid ids -
the adapter surfaces that verbatim instead of guessing.

Config:
    DASHSCOPE_API_KEY   required
    QWEN_MODEL          model id, e.g. ``qwen3-max``
    DASHSCOPE_BASE_URL  default ``https://dashscope.aliyuncs.com/compatible-mode/v1``
                        (``https://dashscope-intl.aliyuncs.com/compatible-mode/v1`` for intl)
"""

from __future__ import annotations

from .base import FRAMEWORK_ADVERSARIAL, FRAMEWORK_PLAN_ACT, HttpChatAdapter, TaskRequest
from .env import env

DEFAULT_MODEL = "qwen3-max"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
INTL_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


class QwenMaxValidator(HttpChatAdapter):
    """Validation agent backed by Qwen via DashScope's OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        name: str = "qwen-planner",
        framework: str = FRAMEWORK_PLAN_ACT,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        region: str = "cn",
        temperature: float = 0.7,
    ) -> None:
        resolved_model = model or env("QWEN_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
        if base_url:
            resolved_url = base_url
        elif region == "intl":
            resolved_url = env("DASHSCOPE_INTL_BASE_URL", INTL_BASE_URL) or INTL_BASE_URL
        else:
            resolved_url = env("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
        super().__init__(
            name=name,
            model=resolved_model,
            provider=f"dashscope-{region}",
            framework=framework,
            base_url=resolved_url,
            api_key=api_key if api_key is not None else env("DASHSCOPE_API_KEY"),
            temperature=temperature,
        )
        self.region = region

    def is_available(self) -> bool:
        return bool(self._api_key)


def qwen_planner(**kwargs: object) -> QwenMaxValidator:
    """Convenience factory: Qwen in plan-then-act mode on the China endpoint."""
    return QwenMaxValidator(name="qwen-planner", framework=FRAMEWORK_PLAN_ACT, region="cn", **kwargs)  # type: ignore[arg-type]


def qwen_red_team(**kwargs: object) -> QwenMaxValidator:
    """Convenience factory: Qwen in adversarial mode on the international endpoint."""
    return QwenMaxValidator(
        name="qwen-red-team", framework=FRAMEWORK_ADVERSARIAL, region="intl", **kwargs  # type: ignore[arg-type]
    )
