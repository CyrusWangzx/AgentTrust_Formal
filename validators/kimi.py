"""Kimi adapter (Moonshot AI, OpenAI-compatible ``/v1/chat/completions``).

Moonshot is the second heterogeneous source in the default cohort (spec 2.6): a different
model family behind a different vendor endpoint, which directly satisfies constraints 1 and
2 of the anti-fake-heterogeneity triad.

The Moonshot model line-up rotates frequently and retired ids return HTTP 404, so the served
id is configuration (``KIMI_MODEL``) rather than a hard-coded constant. ``cohort.yaml``
records the expected family; the adapter reports the vendor error verbatim when the id is
not entitled for the account.

Config:
    MOONSHOT_API_KEY   required
    KIMI_MODEL         model id, e.g. ``kimi-k2.6``
    MOONSHOT_BASE_URL  default ``https://api.moonshot.cn/v1``
                       (``https://api.moonshot.ai/v1`` for the international platform)
"""

from __future__ import annotations

from .base import FRAMEWORK_BREADTH, FRAMEWORK_CHECKLIST, HttpChatAdapter, TaskRequest
from .env import env

DEFAULT_MODEL = "kimi-k2.6"
DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
INTL_BASE_URL = "https://api.moonshot.ai/v1"


class KimiValidator(HttpChatAdapter):
    """Validation agent backed by a Kimi model via the Moonshot platform."""

    def __init__(
        self,
        *,
        name: str = "kimi-auditor",
        framework: str = FRAMEWORK_CHECKLIST,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        region: str = "cn",
        temperature: float = 0.6,
    ) -> None:
        resolved_model = model or env("KIMI_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
        if base_url:
            resolved_url = base_url
        elif region == "intl":
            resolved_url = env("MOONSHOT_INTL_BASE_URL", INTL_BASE_URL) or INTL_BASE_URL
        else:
            resolved_url = env("MOONSHOT_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
        super().__init__(
            name=name,
            model=resolved_model,
            provider=f"moonshot-{region}",
            framework=framework,
            base_url=resolved_url,
            api_key=api_key if api_key is not None else env("MOONSHOT_API_KEY"),
            temperature=temperature,
        )
        self.region = region


def kimi_auditor(**kwargs: object) -> KimiValidator:
    """Convenience factory: Kimi running a constraint checklist audit."""
    return KimiValidator(name="kimi-auditor", framework=FRAMEWORK_CHECKLIST, region="cn", **kwargs)  # type: ignore[arg-type]


def kimi_explorer(**kwargs: object) -> KimiValidator:
    """Convenience factory: Kimi in breadth-first exploration mode (intl endpoint)."""
    return KimiValidator(name="kimi-explorer", framework=FRAMEWORK_BREADTH, region="intl", **kwargs)  # type: ignore[arg-type]
