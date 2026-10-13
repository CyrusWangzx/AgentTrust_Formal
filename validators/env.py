"""Minimal ``.env`` loader.

Kept dependency-free and deliberately tiny: the repository must be reproducible in a clean
environment with only ``pytest`` and ``numpy`` installed. Real secrets live in ``.env``
(never committed); ``.env.example`` carries placeholders only.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Repository root (``validators/`` -> ``..``).
REPO_ROOT = Path(__file__).resolve().parent.parent

_LOADED = False


def load_dotenv(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Load ``KEY=VALUE`` pairs from ``.env`` into ``os.environ``.

    Existing environment variables win unless ``override`` is set, so shell/CI values take
    precedence over the file. Returns the parsed mapping (useful for assertions in tests).
    """
    global _LOADED
    target = Path(path) if path is not None else REPO_ROOT / ".env"
    parsed: dict[str, str] = {}
    if not target.is_file():
        _LOADED = True
        return parsed
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        parsed[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    _LOADED = True
    return parsed


def env(name: str, default: str | None = None) -> str | None:
    """Read an environment variable, loading ``.env`` on first use."""
    if not _LOADED and name not in os.environ:
        load_dotenv()
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def env_float(name: str, default: float) -> float:
    value = env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    value = env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
