"""Central configuration.

Every setting comes from the environment and is validated once at startup so the process
fails fast and loudly rather than silently degrading. ``.env.example`` lists the full set;
real values never enter the repository (quality redline 3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from validators.env import REPO_ROOT, env, env_float, env_int, load_dotenv

#: Monad Testnet. The work order is explicit: testnet is 10143, mainnet is 143.
MONAD_TESTNET_CHAIN_ID = 10143
MONAD_MAINNET_CHAIN_ID = 143
DEFAULT_TESTNET_RPC = "https://testnet-rpc.monad.xyz"
DEFAULT_TESTNET_EXPLORER = "https://testnet.monadscan.com"


class ConfigError(RuntimeError):
    """Raised when the environment is inconsistent or incomplete for the requested mode."""


@dataclass
class Settings:
    """Resolved runtime settings."""

    chain_id: int = MONAD_TESTNET_CHAIN_ID
    rpc_url: str = DEFAULT_TESTNET_RPC
    explorer_url: str = DEFAULT_TESTNET_EXPLORER
    registry_address: str = ""
    requester_private_key: str = ""
    identity_registry_address: str = ""

    d_base_default: float = 0.5
    theta_low: float = 1.5
    theta_high: float = 3.0
    max_rounds: int = 3
    min_usable_validators: int = 2
    terminal_metric: str = "l2"
    cohort_mode: str = "auto"

    artifacts_dir: Path = field(default_factory=lambda: REPO_ROOT / "artifacts")
    chain_mode: str = "dry-run"      # dry-run | live
    log_level: str = "INFO"

    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_signer(self) -> bool:
        return bool(self.requester_private_key)

    @property
    def has_registry(self) -> bool:
        return bool(self.registry_address)

    def validate_for_live_chain(self) -> None:
        """Fail fast when ``--chain live`` is requested without the required inputs."""
        problems: list[str] = []
        if self.chain_id != MONAD_TESTNET_CHAIN_ID and self.chain_id != MONAD_MAINNET_CHAIN_ID:
            problems.append(
                f"CHAIN_ID {self.chain_id} is not a Monad chain id "
                f"(testnet {MONAD_TESTNET_CHAIN_ID}, mainnet {MONAD_MAINNET_CHAIN_ID})"
            )
        if self.chain_id == MONAD_MAINNET_CHAIN_ID:
            problems.append(
                "refusing to run against Monad mainnet (143); the work order requires testnet 10143"
            )
        if not self.rpc_url:
            problems.append("RPC_URL_10143 is required for live chain writes")
        if not self.has_registry:
            problems.append("AGENTTRUST_REGISTRY_ADDRESS is required for live chain writes")
        if not self.has_signer:
            problems.append("DEPLOYER_PRIVATE_KEY is required for live chain writes")
        if problems:
            raise ConfigError("cannot start live chain mode:\n  - " + "\n  - ".join(problems))

    def summary(self) -> dict[str, Any]:
        """Safe-to-log summary: never includes key material."""
        return {
            "chain_id": self.chain_id,
            "rpc_url": self.rpc_url,
            "explorer_url": self.explorer_url,
            "registry_address": self.registry_address or None,
            "identity_registry_address": self.identity_registry_address or None,
            "chain_mode": self.chain_mode,
            "cohort_mode": self.cohort_mode,
            "has_signer": self.has_signer,
            "theta_low": self.theta_low,
            "theta_high": self.theta_high,
            "max_rounds": self.max_rounds,
            "min_usable_validators": self.min_usable_validators,
            "terminal_metric": self.terminal_metric,
            "d_base_default": self.d_base_default,
            "artifacts_dir": str(self.artifacts_dir),
        }


def load_settings(*, require_live_chain: bool = False, env_file: str | Path | None = None) -> Settings:
    """Build :class:`Settings` from the environment, validating when required."""
    load_dotenv(env_file)

    settings = Settings(
        chain_id=env_int("CHAIN_ID", MONAD_TESTNET_CHAIN_ID),
        rpc_url=env("RPC_URL_10143", DEFAULT_TESTNET_RPC) or DEFAULT_TESTNET_RPC,
        explorer_url=env("EXPLORER_URL_10143", DEFAULT_TESTNET_EXPLORER) or DEFAULT_TESTNET_EXPLORER,
        registry_address=env("AGENTTRUST_REGISTRY_ADDRESS", "") or "",
        requester_private_key=env("DEPLOYER_PRIVATE_KEY", "") or "",
        identity_registry_address=env("IDENTITY_REGISTRY_ADDRESS", "") or "",
        d_base_default=env_float("D_BASE_DEFAULT", 0.5),
        theta_low=env_float("THETA_LOW", 1.5),
        theta_high=env_float("THETA_HIGH", 3.0),
        max_rounds=env_int("MAX_ROUNDS", 3),
        min_usable_validators=env_int("MIN_USABLE_VALIDATORS", 2),
        terminal_metric=env("TERMINAL_METRIC", "l2") or "l2",
        cohort_mode=env("COHORT_MODE", "auto") or "auto",
        artifacts_dir=Path(env("ARTIFACTS_DIR", str(REPO_ROOT / "artifacts")) or (REPO_ROOT / "artifacts")),
        chain_mode=env("CHAIN_MODE", "dry-run") or "dry-run",
        log_level=env("LOG_LEVEL", "INFO") or "INFO",
    )

    if settings.theta_high < settings.theta_low:
        raise ConfigError(
            f"THETA_HIGH ({settings.theta_high}) must be >= THETA_LOW ({settings.theta_low})"
        )
    if settings.max_rounds < 1:
        raise ConfigError(f"MAX_ROUNDS must be >= 1, got {settings.max_rounds}")
    if settings.min_usable_validators < 2:
        raise ConfigError(
            f"MIN_USABLE_VALIDATORS must be >= 2 (spec 2.6), got {settings.min_usable_validators}"
        )
    if settings.terminal_metric not in {"l2", "mahalanobis"}:
        raise ConfigError(
            f"TERMINAL_METRIC must be 'l2' or 'mahalanobis', got {settings.terminal_metric!r}"
        )
    if settings.chain_mode not in {"dry-run", "live"}:
        raise ConfigError(f"CHAIN_MODE must be 'dry-run' or 'live', got {settings.chain_mode!r}")

    if require_live_chain:
        settings.validate_for_live_chain()
    return settings


def redact(value: str | None) -> str:
    """Render a secret for logs as ``<set:last4>`` / ``<unset>``."""
    if not value:
        return "<unset>"
    tail = value[-4:] if len(value) >= 4 else ""
    return f"<set:...{tail}>"


def debug_env_keys() -> list[str]:
    """Names of AgentTrust-relevant variables that are currently set (never values)."""
    interesting = [
        "CHAIN_ID", "RPC_URL_10143", "AGENTTRUST_REGISTRY_ADDRESS", "IDENTITY_REGISTRY_ADDRESS",
        "DEPLOYER_PRIVATE_KEY", "DASHSCOPE_API_KEY", "MOONSHOT_API_KEY", "QWEN_MODEL", "KIMI_MODEL",
        "THETA_LOW", "THETA_HIGH", "MAX_ROUNDS", "COHORT_MODE", "CHAIN_MODE",
    ]
    return [name for name in interesting if os.environ.get(name)]
