"""Quota-exhausted error classification.

Per TASKS.md T16a: distinguish "transient rate-limit" (back-off + retry)
from "quota exhausted" (do NOT back off; surface as
``QuotaExhaustedError`` with tier / provider / reset_hint so T16c/T16d
can downgrade or hand off to the OS-level scheduler).

The regex matchers are data-driven via ``config/quota.yaml`` —
providers love to tweak their error strings, so the matching rules
live in config rather than Python.

Public API::

    from harness.quota import (
        QuotaConfig, QuotaExhaustedError, QuotaSignal,
        classify_quota_error, load_quota_config,
    )

    cfg = load_quota_config()                       # default path
    signal = classify_quota_error(text, provider="anthropic", config=cfg)
    if signal is not None:
        raise QuotaExhaustedError(tier="worker", provider=signal.provider,
                                   reset_hint=signal.reset_hint,
                                   message=text)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

import pydantic
import yaml

from harness.adapters.base import AdapterError, QuotaExhaustedError


DEFAULT_QUOTA_CONFIG_PATH = Path(__file__).parent.parent / "config" / "quota.yaml"


# Re-exported here for callers that imported QuotaExhaustedError from
# harness.quota before T16a — the canonical definition lives in
# adapters/base.py so it sits inside the AdapterError hierarchy and the
# retry loop can recognise it without importing quota.
__all__ = [
    "DEFAULT_QUOTA_CONFIG_PATH",
    "ProviderRules",
    "QuotaConfig",
    "QuotaExhaustedError",
    "QuotaSignal",
    "ResetHint",
    "ResetStrategy",
    "classify_quota_error",
    "load_quota_config",
    "next_reset",
]


# ---------------------------------------------------------------------------
# Reset scheduling (T16b)
# ---------------------------------------------------------------------------


class ResetStrategy(str, Enum):
    """Algorithm for ``next_reset`` to pick the next available reset time."""

    FIXED_CLOCK = "fixed_clock"
    ROLLING = "rolling"


class ResetHint(pydantic.BaseModel):
    """Parsed recovery time from a quota error string.

    Either ``reset_at`` (an absolute datetime) or
    ``retry_after_seconds`` (relative offset) may be set, or both.
    ``honor_reset_hint`` controls whether ``next_reset`` prefers the
    hint over the strategy-computed value.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    reset_at: Optional[datetime] = None
    retry_after_seconds: Optional[int] = None
    honor_reset_hint: bool = True


def next_reset(
    strategy: ResetStrategy | str,
    *,
    now: datetime,
    strategy_params: Optional[Mapping[str, Any]] = None,
    hint: Optional[ResetHint] = None,
) -> datetime:
    """Compute when the quota will be available again.

    Pure function — ``now`` is injected from outside so unit tests can
    pin a clock. ``Date.now()`` / ``datetime.utcnow()`` are intentionally
    forbidden in this code path.

    Parameters
    ----------
    strategy
        ``ResetStrategy.FIXED_CLOCK`` or ``ResetStrategy.ROLLING``.
    now
        Current time. Must be timezone-aware.
    strategy_params
        Strategy-specific parameters:
        - ``fixed_clock``: ``anchor_hour`` (int, 0-23) and
          ``interval_hours`` (int > 0).
        - ``rolling``: ``window_hours`` (int > 0).
    hint
        Optional :class:`ResetHint` parsed from the quota signal. When
        set and ``hint.honor_reset_hint`` is True, the hint overrides
        the strategy-computed value.

    Returns
    -------
    datetime
        The next reset instant, timezone-aware, in UTC.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError(
            "next_reset requires a timezone-aware datetime; got naive "
            f"{now!r}"
        )

    # Hint override path (T16b acceptance: hint can come from the
    # provider's own retry-after / resets-at parsing in T16a).
    if hint is not None and hint.honor_reset_hint:
        if hint.reset_at is not None:
            return _ensure_utc(hint.reset_at)
        if hint.retry_after_seconds is not None:
            return now + timedelta(seconds=int(hint.retry_after_seconds))

    # Strategy path.
    if isinstance(strategy, str):
        try:
            strategy = ResetStrategy(strategy)
        except ValueError as exc:
            raise ValueError(
                f"Unknown reset strategy: {strategy!r}. "
                f"Expected one of {[s.value for s in ResetStrategy]}"
            ) from exc

    params = dict(strategy_params or {})

    if strategy == ResetStrategy.FIXED_CLOCK:
        interval = params.get("interval_hours")
        if interval is None:
            raise ValueError(
                "FIXED_CLOCK strategy requires 'interval_hours' in "
                "strategy_params"
            )
        anchor_hour = int(params.get("anchor_hour", 0))
        return _next_fixed_clock_boundary(now, anchor_hour, int(interval))

    if strategy == ResetStrategy.ROLLING:
        window = params.get("window_hours")
        if window is None:
            raise ValueError(
                "ROLLING strategy requires 'window_hours' in strategy_params"
            )
        return now + timedelta(hours=int(window))

    raise ValueError(f"Unknown reset strategy: {strategy!r}")


def _next_fixed_clock_boundary(
    now: datetime,
    anchor_hour: int,
    interval_hours: int,
) -> datetime:
    """Return the smallest boundary ``>= now``.

    Boundaries occur at ``anchor_hour``, ``anchor_hour + interval``,
    ``anchor_hour + 2*interval``, …, capped to a single 24h day. After
    the last boundary of the day the cycle restarts at ``anchor_hour``
    of the next day — so for ``anchor=0, interval=5`` the boundaries
    are 00:00, 05:00, 10:00, 15:00, 20:00 (per day); at 23:30 the
    next boundary is 00:00 of the following day, not 01:00.
    """
    if interval_hours <= 0:
        raise ValueError(
            f"interval_hours must be > 0, got {interval_hours}"
        )

    anchor_hour = anchor_hour % 24

    # Compute the absolute boundary timestamps for today + tomorrow
    # (anchored at UTC, matching the tz-aware `now`).
    today_anchor = now.replace(
        hour=anchor_hour, minute=0, second=0, microsecond=0
    )
    boundaries: list[datetime] = []
    for i in range(24 // interval_hours + 1):
        boundary = today_anchor + timedelta(hours=i * interval_hours)
        if boundary > now:
            boundaries.append(boundary)

    if not boundaries:
        # All today's boundaries are behind us → first one tomorrow.
        tomorrow_anchor = today_anchor + timedelta(days=1)
        boundaries.append(tomorrow_anchor)

    return min(boundaries)


def _ensure_utc(dt: datetime) -> datetime:
    """Coerce a possibly-tz-naive datetime into UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ProviderRules(pydantic.BaseModel):
    """Matcher patterns + reset-hint extraction rules for one provider."""

    model_config = pydantic.ConfigDict(frozen=True)

    patterns: list[str] = pydantic.Field(default_factory=list)
    reset_hint: dict[str, str] = pydantic.Field(default_factory=dict)


class QuotaConfig(pydantic.BaseModel):
    """Top-level ``config/quota.yaml`` schema."""

    model_config = pydantic.ConfigDict(frozen=True)

    providers: dict[str, ProviderRules] = pydantic.Field(default_factory=dict)


class QuotaSignal(pydantic.BaseModel):
    """Result of matching an error string against the quota patterns."""

    model_config = pydantic.ConfigDict(frozen=True)

    provider: str
    matched_pattern: str
    reset_hint: Optional[str] = None
    retry_after_seconds: Optional[int] = None


def load_quota_config(path: Optional[Path] = None) -> QuotaConfig:
    """Load ``config/quota.yaml`` and validate it.

    Parameters
    ----------
    path
        Optional explicit path. Defaults to
        ``config/quota.yaml`` next to the harness package.
    """
    cfg_path = Path(path) if path is not None else DEFAULT_QUOTA_CONFIG_PATH
    if not cfg_path.exists():
        # No config on disk → empty table. classify_quota_error() will
        # then return None for every input (safe no-op), which means
        # T16a gracefully degrades until operators populate the file.
        return QuotaConfig()
    raw = yaml.safe_load(cfg_path.read_text()) or {}
    return QuotaConfig.model_validate(raw)


def classify_quota_error(
    text: str,
    *,
    provider: str,
    config: QuotaConfig,
) -> Optional[QuotaSignal]:
    """Return a ``QuotaSignal`` if ``text`` matches the provider's quota patterns.

    Parameters
    ----------
    text
        The error string to inspect (typically ``stderr`` from a
        subprocess, or the JSON ``error`` field of a structured envelope).
    provider
        Logical provider name (``anthropic``, ``MiniMax``, ...). Lookup
        is case-insensitive.
    config
        Loaded :class:`QuotaConfig`. The caller is expected to have
        loaded this once at startup and reuse it.

    Returns
    -------
    Optional[QuotaSignal]
        ``None`` when the text does not match any quota pattern — caller
        should fall back to its normal error-classification path.
    """
    if not text:
        return None

    # Case-insensitive provider lookup.
    rules: Optional[ProviderRules] = None
    if config.providers:
        lowered = provider.lower()
        for name, r in config.providers.items():
            if name.lower() == lowered:
                rules = r
                break

    if rules is None or not rules.patterns:
        return None

    matched_pattern: Optional[str] = None
    for pattern in rules.patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            matched_pattern = pattern
            break

    if matched_pattern is None:
        return None

    reset_hint, retry_after_seconds = _extract_reset_hint(text, rules.reset_hint)

    return QuotaSignal(
        provider=provider,
        matched_pattern=matched_pattern,
        reset_hint=reset_hint,
        retry_after_seconds=retry_after_seconds,
    )


def _extract_reset_hint(
    text: str,
    hint_specs: Mapping[str, str],
) -> tuple[Optional[str], Optional[int]]:
    """Pull ``retry_after`` / ``resets_at`` out of the error text per spec.

    Returns ``(reset_hint_text, retry_after_seconds)``. ``retry_after_seconds``
    is parsed as an integer when the matching pattern is the
    ``retry_after`` rule; otherwise we return the reset text from
    whichever rule fired first.
    """
    retry_seconds: Optional[int] = None
    reset_text: Optional[str] = None

    if "retry_after" in hint_specs:
        m = re.search(hint_specs["retry_after"], text, flags=re.IGNORECASE)
        if m:
            try:
                retry_seconds = int(m.group(1))
                reset_text = f"retry_after={retry_seconds}s"
            except (ValueError, IndexError):
                pass

    if reset_text is None and "resets_at" in hint_specs:
        m = re.search(hint_specs["resets_at"], text, flags=re.IGNORECASE)
        if m:
            reset_text = f"resets_at={m.group(1)}"

    return reset_text, retry_seconds