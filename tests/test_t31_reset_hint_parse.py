"""T31 Bug A — prefixed reset_hint must not crash enter_quota_hold.

Production code (``harness/quota.py::_extract_reset_hint``) emits
``reset_hint`` as the literal string ``"resets_at=<iso>"`` so the
quota classifier can log/display it. But the same field is then
fed into :class:`ResetHint` (``reset_at: Optional[datetime]``) inside
``enter_quota_hold`` — and pydantic will not parse ``"resets_at=..."``
as a datetime, so the very moment we need to write a hold we crash.

The fix lives in :func:`harness.quota_hold.enter_quota_hold`: strip the
optional ``resets_at=`` / ``retry_after=`` / ``resume_at=`` prefix
before passing the remainder to :class:`ResetHint`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.adapters.base import QuotaExhaustedError
from harness.quota_hold import (
    HOLD_RELATIVE_PATH,
    enter_quota_hold,
    read_hold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_hold_json(project_dir: Path) -> dict:
    """Read the raw on-disk hold JSON, no model validation."""
    raw_path = project_dir / HOLD_RELATIVE_PATH
    assert raw_path.exists(), f"hold file missing at {raw_path}"
    return json.loads(raw_path.read_text())


# ---------------------------------------------------------------------------
# Bug A: prefixed reset_hint must be parsed, not raise
# ---------------------------------------------------------------------------


class TestPrefixedResetHint:
    """``enter_quota_hold`` must accept the production-form reset_hint."""

    def test_prefixed_resets_at_with_z_suffix_is_parsed(self, tmp_path):
        """The most common production form: ``resets_at=<iso>Z``."""
        exc = QuotaExhaustedError(
            "usage limit reached for MiniMax",
            tier="worker",
            provider="MiniMax",
            reset_hint="resets_at=2026-07-08T10:00:00Z",
        )
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.return_value = "launchd"
            path = enter_quota_hold(tmp_path, exc)

        # Hold must have been written — current code raises ValidationError here.
        assert path.exists()
        restored = read_hold(tmp_path)
        assert restored is not None
        # resume_at should be the parsed iso, not the raw prefixed string.
        expected = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)
        assert restored.resume_at == expected

    def test_prefixed_resets_at_with_offset_is_parsed(self, tmp_path):
        """Same prefix, but with a numeric UTC offset rather than ``Z``."""
        exc = QuotaExhaustedError(
            "usage limit reached",
            tier="worker",
            provider="anthropic",
            reset_hint="resets_at=2026-07-08T10:00:00+00:00",
        )
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.return_value = "launchd"
            path = enter_quota_hold(tmp_path, exc)

        assert path.exists()
        restored = read_hold(tmp_path)
        assert restored is not None
        # The instant must be 10:00 UTC; offset parsing must not introduce drift.
        assert restored.resume_at.utcoffset().total_seconds() == 0
        assert restored.resume_at.hour == 10
        assert restored.resume_at.minute == 0

    def test_prefixed_retry_after_falls_through_gracefully(self, tmp_path):
        """``retry_after=3600s`` style hints have no datetime — should be
        passed via :class:`ResetHint.retry_after_seconds` instead and
        not be misinterpreted as a reset time."""
        exc = QuotaExhaustedError(
            "rate_limit_error ... retry-after: 3600",
            tier="worker",
            provider="anthropic",
            reset_hint="retry_after=3600s",
            retry_after_seconds=3600,
        )
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.return_value = "launchd"
            path = enter_quota_hold(tmp_path, exc)

        # The hold must still be written and a wake-up still scheduled
        # (the retry_after seconds path always yields a valid resume_at).
        assert path.exists()
        restored = read_hold(tmp_path)
        assert restored is not None
        # resume_at must be in the future (now + 1h ish) — not the raw string.
        now = datetime.now(timezone.utc)
        delta = (restored.resume_at - now).total_seconds()
        assert 0 < delta < 7200, f"resume_at should be ~3600s in the future, got delta={delta}"

    def test_unprefixed_iso_reset_hint_still_works(self, tmp_path):
        """Backwards compatibility: a bare ISO string (no ``resets_at=`` prefix)
        must still be accepted. The fix is to *strip* the prefix when present;
        the bare form must keep working."""
        exc = QuotaExhaustedError(
            "usage limit reached",
            tier="worker",
            provider="anthropic",
            reset_hint="2026-07-08T10:00:00+00:00",
        )
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.return_value = "launchd"
            path = enter_quota_hold(tmp_path, exc)

        assert path.exists()
        restored = read_hold(tmp_path)
        assert restored is not None
        assert restored.resume_at.utcoffset().total_seconds() == 0
        assert restored.resume_at.hour == 10

    def test_no_reset_hint_at_all_uses_strategy(self, tmp_path):
        """When ``reset_hint`` and ``retry_after_seconds`` are both None,
        ``enter_quota_hold`` must fall back to the strategy math
        (rolling window) — no exception, valid hold."""
        exc = QuotaExhaustedError(
            "usage limit reached",
            tier="worker",
            provider="anthropic",
        )
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.return_value = "launchd"
            path = enter_quota_hold(tmp_path, exc)

        assert path.exists()
        restored = read_hold(tmp_path)
        assert restored is not None
        # rolling strategy default: now + window_hours=5
        now = datetime.now(timezone.utc)
        delta = (restored.resume_at - now).total_seconds()
        # 5h ± 60s
        assert 5 * 3600 - 60 < delta < 5 * 3600 + 60

    def test_garbage_reset_hint_does_not_crash_enter_quota_hold(self, tmp_path):
        """An unparseable string must NOT raise — the hold is critical
        even when the hint is malformed. Fall back to the strategy."""
        exc = QuotaExhaustedError(
            "usage limit reached",
            tier="worker",
            provider="anthropic",
            reset_hint="totally not a date",
        )
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.return_value = "launchd"
            # Must not raise — the hold is the source of truth, even
            # with a garbage hint we must persist something.
            path = enter_quota_hold(tmp_path, exc)

        assert path.exists()
        restored = read_hold(tmp_path)
        assert restored is not None


# ---------------------------------------------------------------------------
# Sanity: the existing T16e prefix-strip test still works after the fix
# ---------------------------------------------------------------------------


class TestExistingContractPreserved:
    def test_enter_quota_hold_writes_at_path(self, tmp_path):
        """The file location contract is unchanged."""
        exc = QuotaExhaustedError(
            "usage limit reached",
            tier="worker",
            provider="MiniMax",
            reset_hint="resets_at=2026-07-08T10:00:00+00:00",
        )
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.return_value = "launchd"
            path = enter_quota_hold(tmp_path, exc)

        assert path == tmp_path / HOLD_RELATIVE_PATH
