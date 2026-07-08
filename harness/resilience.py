"""Central resilience configuration (T34).

Before T34, retry / timeout / quota knobs were scattered across:

- ``harness/adapters/base.py::RETRY_BASE_DELAY=1.0``,
  ``RETRY_MAX_DELAY=32``, ``RETRY_MAX_ATTEMPTS=3``
- ``harness/adapters/claude.py::RETRY_BASE_DELAY=2.0`` (overrides base)
- ``harness/generator.py::GENERATOR_TIMEOUT_SECONDS=300``
- ``harness/reviewer_runner.py::REVIEWER_TIMEOUT_SECONDS=180``
- ``harness/visual_reviewer.py::navigation_timeout_ms=15000`` + 1.5s connect
- ``harness/quota_hold.py::MAX_AUTO_RESUME=3`` + ``window_hours=5``

This module pulls all of those into a single pydantic model loaded
from ``config/resilience.yaml`` (overrideable via env vars).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pydantic
import yaml


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TimeoutsConfig(pydantic.BaseModel):
    """Per-stage subprocess / call timeouts (seconds; ``visual`` is ms)."""

    model_config = pydantic.ConfigDict(frozen=True)

    agent: int = 600
    generator: int = 300
    reviewer: int = 180
    visual: int = 15000  # milliseconds (Playwright)
    quota: int = 30


class RetryConfig(pydantic.BaseModel):
    """Exponential back-off knobs. ``jitter_ratio`` in [0, 1]."""

    model_config = pydantic.ConfigDict(frozen=True)

    base_delay_seconds: float = 1.0
    max_attempts: int = 3
    max_delay_seconds: float = 32.0
    jitter_ratio: float = 0.25


class QuotaConfig(pydantic.BaseModel):
    """Quota-hold scheduling knobs."""

    model_config = pydantic.ConfigDict(frozen=True)

    window_hours: int = 5
    max_auto_resume: int = 3


class ResilienceConfig(pydantic.BaseModel):
    """Top-level: a single object holds every resilience knob."""

    model_config = pydantic.ConfigDict(frozen=True)

    timeouts: TimeoutsConfig = pydantic.Field(default_factory=TimeoutsConfig)
    retry: RetryConfig = pydantic.Field(default_factory=RetryConfig)
    quota: QuotaConfig = pydantic.Field(default_factory=QuotaConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _apply_env_overrides(cfg: ResilienceConfig) -> ResilienceConfig:
    """Overlay env vars on top of the parsed cfg.

    Convention: ``AUTODEV_<SECTION>_<FIELD>`` (uppercased, dots → underscores).
    The env value is coerced to int / float where the field type demands it.
    Unknown env keys are silently ignored so a typo doesn't break boot.
    """
    # Map env-prefix → pydantic field name on the parent. The env
    # convention is upper-case; pydantic field names are lower-case.
    sections: list[tuple[str, str, object]] = [
        ("TIMEOUTS", "timeouts", cfg.timeouts),
        ("RETRY", "retry", cfg.retry),
        ("QUOTA", "quota", cfg.quota),
    ]
    new_sections: dict[str, object] = {}
    for env_prefix, field_name, section in sections:
        new_fields: dict[str, object] = {}
        for f_name, field_info in type(section).model_fields.items():
            env_key = f"AUTODEV_{env_prefix}_{f_name.upper()}"
            raw = os.environ.get(env_key)
            if raw is None:
                continue
            annotation = field_info.annotation
            try:
                if annotation is int or annotation == int:
                    coerced: object = int(raw)
                elif annotation is float or annotation == float:
                    coerced = float(raw)
                else:
                    coerced = raw
            except (TypeError, ValueError):
                # Bad env value — ignore (operator can fix and re-run).
                # We don't raise here: a single bad override shouldn't
                # wedge the entire harness boot.
                continue
            new_fields[f_name] = coerced
        if new_fields:
            new_sections[field_name] = section.model_copy(update=new_fields)
        else:
            new_sections[field_name] = section

    return cfg.model_copy(update=new_sections)


def load_resilience_config(path: Optional[Path] = None) -> ResilienceConfig:
    """Load resilience config from yaml, overlay env, return parsed.

    Parameters
    ----------
    path
        Path to a yaml file with the schema documented in
        ``config/resilience.yaml``. When ``None`` (or the file is
        missing), the function falls back to :class:`ResilienceConfig`'s
        built-in defaults so the harness still boots.
    """
    if path is None:
        harness_root = Path(__file__).parent.parent
        path = harness_root / "config" / "resilience.yaml"

    raw: dict = {}
    if path.exists():
        with path.open() as fh:
            raw = yaml.safe_load(fh) or {}

    cfg = ResilienceConfig.model_validate(raw)
    return _apply_env_overrides(cfg)


# ---------------------------------------------------------------------------
# Singleton accessor (lazy)
# ---------------------------------------------------------------------------


_cached: Optional[ResilienceConfig] = None


def get_resilience_config() -> ResilienceConfig:
    """Return the process-wide resilience config, loading on first use.

    Tests that need a custom config should pass an explicit path to
    :func:`load_resilience_config` rather than mutating this cache.
    """
    global _cached
    if _cached is None:
        _cached = load_resilience_config()
    return _cached


def reset_resilience_cache() -> None:
    """Drop the cached config — useful in tests that change env vars."""
    global _cached
    _cached = None
