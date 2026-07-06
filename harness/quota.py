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
from pathlib import Path
from typing import Mapping, Optional

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
    "classify_quota_error",
    "load_quota_config",
]


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