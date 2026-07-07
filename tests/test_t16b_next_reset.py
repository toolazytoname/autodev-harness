"""RED tests for T16b — next_reset pure function.

Per TASKS.md T16b: a pure function ``next_reset(strategy, now, hint)``
returns the datetime at which a quota will be available again, used by
T16d to schedule the OS-level wake-up. Two strategies:

- ``fixed_clock`` — MiniMax-style: anchor at 00:00 + interval_hours
  boundary. Take the smallest boundary >= now.
- ``rolling`` — Anthropic-style: now + window_hours.

A ``ResetHint`` from a parsed quota signal (retry-after seconds or
"resets at <iso>") overrides the strategy when ``honor_reset_hint`` is
True. ``now`` is injected from outside so the function is testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from harness.quota import (
    ResetHint,
    ResetStrategy,
    next_reset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test: fixed_clock strategy
# ---------------------------------------------------------------------------


class TestFixedClockStrategy:
    def test_returns_next_boundary_after_now(self):
        # Anchor 00:00 UTC, 5h interval. now=01:30 → next boundary 05:00.
        now = _at(2026, 7, 7, 1, 30)
        result = next_reset(
            ResetStrategy.FIXED_CLOCK,
            now=now,
            strategy_params={
                "anchor_hour": 0,
                "interval_hours": 5,
            },
        )
        assert result == _at(2026, 7, 7, 5)

    def test_returns_next_boundary_at_exact_boundary(self):
        # now exactly at a boundary → next one, not now.
        now = _at(2026, 7, 7, 5)
        result = next_reset(
            ResetStrategy.FIXED_CLOCK,
            now=now,
            strategy_params={"anchor_hour": 0, "interval_hours": 5},
        )
        assert result == _at(2026, 7, 7, 10)

    def test_crosses_midnight(self):
        # now=23:30 with anchor 0, interval 5 → next boundary 00:00 next day.
        now = _at(2026, 7, 7, 23, 30)
        result = next_reset(
            ResetStrategy.FIXED_CLOCK,
            now=now,
            strategy_params={"anchor_hour": 0, "interval_hours": 5},
        )
        assert result == _at(2026, 7, 8, 0)

    def test_custom_anchor_hour(self):
        # Anchor at 03:00, interval 6h. now=04:00 → next 09:00.
        now = _at(2026, 7, 7, 4)
        result = next_reset(
            ResetStrategy.FIXED_CLOCK,
            now=now,
            strategy_params={"anchor_hour": 3, "interval_hours": 6},
        )
        assert result == _at(2026, 7, 7, 9)


# ---------------------------------------------------------------------------
# Test: rolling strategy
# ---------------------------------------------------------------------------


class TestRollingStrategy:
    def test_rolling_returns_now_plus_window(self):
        now = _at(2026, 7, 7, 10)
        result = next_reset(
            ResetStrategy.ROLLING,
            now=now,
            strategy_params={"window_hours": 5},
        )
        assert result == _at(2026, 7, 7, 15)

    def test_rolling_custom_window(self):
        now = _at(2026, 7, 7, 10)
        result = next_reset(
            ResetStrategy.ROLLING,
            now=now,
            strategy_params={"window_hours": 24},
        )
        assert result == _at(2026, 7, 8, 10)


# ---------------------------------------------------------------------------
# Test: hint overrides strategy
# ---------------------------------------------------------------------------


class TestHintOverride:
    def test_retry_after_seconds_overrides_strategy(self):
        now = _at(2026, 7, 7, 10)
        hint = ResetHint(retry_after_seconds=3600, honor_reset_hint=True)
        result = next_reset(
            ResetStrategy.FIXED_CLOCK,
            now=now,
            strategy_params={"anchor_hour": 0, "interval_hours": 5},
            hint=hint,
        )
        assert result == _at(2026, 7, 7, 11)

    def test_resets_at_overrides_strategy(self):
        now = _at(2026, 7, 7, 10)
        target = _at(2026, 7, 7, 13, 45)
        hint = ResetHint(reset_at=target, honor_reset_hint=True)
        result = next_reset(
            ResetStrategy.ROLLING,
            now=now,
            strategy_params={"window_hours": 5},
            hint=hint,
        )
        assert result == target

    def test_honor_reset_hint_false_uses_strategy(self):
        # honor_reset_hint=False → strategy path wins even when hint set.
        now = _at(2026, 7, 7, 10)
        hint = ResetHint(retry_after_seconds=60, honor_reset_hint=False)
        result = next_reset(
            ResetStrategy.ROLLING,
            now=now,
            strategy_params={"window_hours": 5},
            hint=hint,
        )
        assert result == _at(2026, 7, 7, 15)


# ---------------------------------------------------------------------------
# Test: error handling
# ---------------------------------------------------------------------------


class TestErrors:
    def test_unknown_strategy_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown reset strategy"):
            next_reset(
                "not-a-strategy",  # type: ignore[arg-type]
                now=_at(2026, 7, 7, 10),
            )

    def test_fixed_clock_requires_interval_hours(self):
        with pytest.raises(ValueError, match="interval_hours"):
            next_reset(
                ResetStrategy.FIXED_CLOCK,
                now=_at(2026, 7, 7, 10),
                strategy_params={"anchor_hour": 0},
            )

    def test_naive_datetime_raises(self):
        # Function should reject naive datetimes; timezone is required.
        naive = datetime(2026, 7, 7, 10)
        with pytest.raises(ValueError, match="timezone"):
            next_reset(
                ResetStrategy.ROLLING,
                now=naive,  # type: ignore[arg-type]
                strategy_params={"window_hours": 5},
            )