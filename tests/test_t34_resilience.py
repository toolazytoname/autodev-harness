"""T34 — central resilience config + retry-after hint + jitter.

Background
----------
Pre-T34, retry/timeout knobs are scattered:

- ``harness/adapters/base.py::RETRY_BASE_DELAY=1.0``,
  ``RETRY_MAX_DELAY=32``, ``RETRY_MAX_ATTEMPTS=3``
- ``harness/adapters/claude.py::RETRY_BASE_DELAY=2.0`` (overrides base)
- ``harness/generator.py::GENERATOR_TIMEOUT_SECONDS=300``
- ``harness/reviewer_runner.py::REVIEWER_TIMEOUT_SECONDS=180``
- ``harness/visual_reviewer.py::navigation_timeout_ms=15000`` + 1.5s connect
- ``harness/quota_hold.py::MAX_AUTO_RESUME=3`` + ``window_hours=5``

Three architectural-review agents all flagged:

1. ``_backoff_delay`` ignores the provider's ``retry_after_seconds`` hint.
2. No jitter — every retry in a fleet hits the API at the exact same instant.
3. No single source of truth — operators can't tune all retry knobs from
   one file.

T34 fixes this by:

1. Adding ``harness/resilience.py::ResilienceConfig`` (pydantic).
2. Reading it from ``config/resilience.yaml`` (overrideable via env).
3. Honoring ``RateLimitError.retry_after_seconds`` in ``_backoff_delay``.
4. Adding ``jitter_ratio`` to break thundering-herd alignment.
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from harness.adapters.base import AdapterBase, RateLimitError
from harness.resilience import ResilienceConfig, load_resilience_config


# ---------------------------------------------------------------------------
# 1. ResilienceConfig schema + load
# ---------------------------------------------------------------------------


class TestResilienceConfigLoad:
    """Loading from a yaml file + env overrides follows the
    "yaml default < env override" priority used elsewhere in the harness."""

    def test_load_from_yaml(self, tmp_path):
        yaml = tmp_path / "resilience.yaml"
        yaml.write_text(dedent("""
            timeouts:
              agent: 600
              generator: 300
              reviewer: 180
              visual: 15000
              quota: 30
            retry:
              base_delay_seconds: 1.0
              max_attempts: 3
              max_delay_seconds: 32
              jitter_ratio: 0.25
            quota:
              window_hours: 5
              max_auto_resume: 3
        """))
        cfg = load_resilience_config(yaml)
        assert cfg.timeouts.agent == 600
        assert cfg.timeouts.generator == 300
        assert cfg.retry.max_attempts == 3
        assert cfg.retry.jitter_ratio == 0.25
        assert cfg.quota.max_auto_resume == 3

    def test_defaults_when_file_missing(self, tmp_path):
        """No file → sane defaults so the harness still boots."""
        cfg = load_resilience_config(tmp_path / "does-not-exist.yaml")
        # All values are concrete defaults (no None) so call-sites can
        # rely on them being present.
        assert cfg.retry.max_attempts > 0
        assert cfg.retry.base_delay_seconds > 0
        assert cfg.retry.max_delay_seconds > 0
        assert 0 <= cfg.retry.jitter_ratio <= 1
        assert cfg.quota.max_auto_resume > 0

    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        """An env var beats the yaml value for the same key.
        Convention: ``AUTODEV_RETRY_<FIELD>`` / ``AUTODEV_TIMEOUT_<SECTION_FIELD>``
        / ``AUTODEV_QUOTA_<FIELD>`` (uppercase)."""
        yaml = tmp_path / "resilience.yaml"
        yaml.write_text(dedent("""
            retry:
              base_delay_seconds: 1.0
              max_attempts: 3
              max_delay_seconds: 32
              jitter_ratio: 0.25
            quota:
              window_hours: 5
              max_auto_resume: 3
        """))
        monkeypatch.setenv("AUTODEV_RETRY_MAX_ATTEMPTS", "7")
        monkeypatch.setenv("AUTODEV_QUOTA_MAX_AUTO_RESUME", "10")

        cfg = load_resilience_config(yaml)
        assert cfg.retry.max_attempts == 7, "env must beat yaml"
        assert cfg.quota.max_auto_resume == 10, "env must beat yaml"
        # Untouched fields fall through to yaml.
        assert cfg.retry.base_delay_seconds == 1.0


# ---------------------------------------------------------------------------
# 2. _backoff_delay honors RateLimitError.retry_after_seconds
# ---------------------------------------------------------------------------


class _ProbeAdapter(AdapterBase):
    """Minimal adapter exposing _backoff_delay for inspection."""

    def _execute(self, *args, **kwargs):  # pragma: no cover - never called
        raise NotImplementedError


class TestBackoffDelayRetryAfterHint:
    """When the adapter raises a 429 with ``retry_after_seconds`` set,
    ``_backoff_delay`` should prefer the provider's hint over the
    raw exponential schedule (capped by ``max_delay_seconds``)."""

    def test_provider_retry_after_used_with_jitter_bounds(self, monkeypatch):
        monkeypatch.setattr("random.uniform", lambda lo, hi: hi)  # worst case
        adapter = _ProbeAdapter()
        # 10s hint, max_delay 32s → result should be 10*(1+jitter)=12.5 max
        delay = adapter._backoff_delay(
            attempt=0,
            retry_after_seconds=10,
            base_delay=1.0,
            max_delay=32.0,
            jitter_ratio=0.25,
        )
        # hi=0.25 (worst case from monkeypatched random.uniform)
        expected = min(10.0, 32.0) * (1 + 0.25)
        assert delay == expected, (
            f"expected {expected} (10s hint * (1+0.25 jitter) upper bound), got {delay}"
        )

    def test_provider_retry_after_clamped_to_max(self, monkeypatch):
        """A 999s hint must be capped by max_delay."""
        monkeypatch.setattr("random.uniform", lambda lo, hi: 0.0)  # no jitter
        adapter = _ProbeAdapter()
        delay = adapter._backoff_delay(
            attempt=2,
            retry_after_seconds=999,
            base_delay=1.0,
            max_delay=32.0,
            jitter_ratio=0.25,
        )
        assert delay == 32.0, f"max_delay must clamp the hint; got {delay}"

    def test_no_retry_after_falls_back_to_exponential(self, monkeypatch):
        """No hint → classic exponential back-off (×jitter)."""
        monkeypatch.setattr("random.uniform", lambda lo, hi: 0.0)
        adapter = _ProbeAdapter()
        # attempt=2 → 1.0 * 2^2 = 4.0
        delay = adapter._backoff_delay(
            attempt=2,
            retry_after_seconds=None,
            base_delay=1.0,
            max_delay=32.0,
            jitter_ratio=0.25,
        )
        assert delay == 4.0


# ---------------------------------------------------------------------------
# 3. Jitter breaks thundering-herd alignment
# ---------------------------------------------------------------------------


class TestJitterBreaksThunderingHerd:
    """Without jitter, every retry in a 1000-worker fleet lands on the
    provider at the same instant — worsening the very overload that
    caused the 429. Jitter spreads the retries uniformly in [-r, +r]
    around the base delay."""

    def test_at_least_five_distinct_values_across_100_calls(self, monkeypatch):
        """100 calls to ``_backoff_delay`` should yield ≥5 distinct
        values (sanity: jitter is real, not a constant)."""
        # Use real random for this test — we want genuine distribution.
        monkeypatch.setattr("random.uniform", random.uniform)
        adapter = _ProbeAdapter()
        values = {
            adapter._backoff_delay(
                attempt=1,
                retry_after_seconds=None,
                base_delay=1.0,
                max_delay=32.0,
                jitter_ratio=0.25,
            )
            for _ in range(100)
        }
        assert len(values) >= 5, (
            f"jitter must produce at least 5 distinct delays; got {len(values)}: {values}"
        )

    def test_jitter_stays_within_ratio_bounds(self, monkeypatch):
        """Sample max jitter and verify it stays within ``±ratio`` of base."""
        # Pin random.uniform to its maximum end so the result is the
        # worst case the user could ever see.
        monkeypatch.setattr("random.uniform", lambda lo, hi: hi)
        adapter = _ProbeAdapter()
        base = 1.0
        ratio = 0.25
        delay = adapter._backoff_delay(
            attempt=0,
            retry_after_seconds=None,
            base_delay=base,
            max_delay=32.0,
            jitter_ratio=ratio,
        )
        # attempt=0 → 1.0 * 2^0 = 1.0; +25% jitter → 1.25
        assert delay == 1.25, f"jitter upper bound: expected 1.25, got {delay}"


# ---------------------------------------------------------------------------
# 4. Default ResilienceConfig is the single source of truth
# ---------------------------------------------------------------------------


class TestResilienceConfigIsExported:
    def test_resilience_config_importable(self):
        from harness.resilience import ResilienceConfig  # noqa: F401

    def test_load_resilience_config_importable(self):
        from harness.resilience import load_resilience_config  # noqa: F401

    def test_config_yaml_exists(self):
        """The shipping config/resilience.yaml must exist and parse."""
        path = Path(__file__).parent.parent / "config" / "resilience.yaml"
        assert path.exists(), f"{path} missing"
        cfg = load_resilience_config(path)
        assert cfg.retry.max_attempts > 0
        assert cfg.timeouts.agent > 0
