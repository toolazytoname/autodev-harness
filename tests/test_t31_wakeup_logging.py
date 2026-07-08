"""T31 Bug B — register_wakeup failure must be logged, not silently swallowed.

Current :func:`harness.quota_hold.enter_quota_hold` wraps the
``register_wakeup`` call in ``except Exception: pass`` so the hold file
is always written. The downside: if the OS scheduler (launchd / systemd
/ at) fails to register, **no one will ever re-launch the pipeline** —
the operator has no signal that anything is wrong, and the hold sits
there until manual ``--continue``.

The fix:

1. Replace the bare ``except: pass`` with a logger.error(..., exc_info=True)
   so the failure is visible in ``logs/harness.log``.
2. Persist ``wakeup_registered: bool`` on the on-disk :class:`QuotaHold`
   so :func:`format_hold_status` / ``harness status`` can surface
   "operator must --continue manually" when it's ``False``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.adapters.base import QuotaExhaustedError
from harness.quota_hold import (
    HOLD_RELATIVE_PATH,
    QuotaHold,
    enter_quota_hold,
    format_hold_status,
    read_hold,
    write_hold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_raw_hold(project_dir: Path) -> dict:
    raw_path = project_dir / HOLD_RELATIVE_PATH
    return json.loads(raw_path.read_text())


def _exc(**overrides):
    defaults = dict(
        message="usage limit reached",
        tier="worker",
        provider="anthropic",
    )
    defaults.update(overrides)
    return QuotaExhaustedError(**defaults)


# ---------------------------------------------------------------------------
# Bug B: register_wakeup failure must be logged, not swallowed
# ---------------------------------------------------------------------------


class TestWakeupFailureIsLoud:
    """When the OS scheduler refuses to register a wake-up, the failure
    must be visible in logs and reflected in the on-disk hold."""

    def test_register_wakeup_runtime_error_is_logged(self, tmp_path, caplog):
        """A RuntimeError from register_wakeup → logger.error called with exc_info."""
        exc = _exc(reset_hint="resets_at=2026-07-08T10:00:00+00:00")
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.side_effect = RuntimeError("launchd not available")
            with caplog.at_level(logging.ERROR, logger="harness.quota_hold"):
                path = enter_quota_hold(tmp_path, exc)

        # Hold file must still be written (we don't want to lose the
        # record just because the OS scheduler failed).
        assert path.exists()

        # AND the failure must be logged.
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, "expected an ERROR log when register_wakeup fails"
        # The message must mention manual --continue so operators find it.
        joined = " ".join(r.getMessage() for r in error_records)
        assert "--continue" in joined or "manual" in joined.lower()
        # exc_info=True → the original RuntimeError is preserved on the log record.
        assert any(r.exc_info is not None for r in error_records), (
            "logger.error should carry exc_info so the traceback survives"
        )

    def test_hold_records_wakeup_registered_false(self, tmp_path):
        """The on-disk hold JSON must carry ``wakeup_registered: false``."""
        exc = _exc(reset_hint="resets_at=2026-07-08T10:00:00+00:00")
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.side_effect = RuntimeError("systemd not reachable")
            enter_quota_hold(tmp_path, exc)

        raw = _read_raw_hold(tmp_path)
        assert "wakeup_registered" in raw, (
            "hold JSON must include wakeup_registered field"
        )
        assert raw["wakeup_registered"] is False

    def test_hold_records_wakeup_registered_true_on_success(self, tmp_path):
        """When the wake-up registers, the field must be ``True`` —
        otherwise the operator sees a permanent warning on every status."""
        exc = _exc(reset_hint="resets_at=2026-07-08T10:00:00+00:00")
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.return_value = "launchd"
            enter_quota_hold(tmp_path, exc)

        raw = _read_raw_hold(tmp_path)
        assert raw.get("wakeup_registered") is True

    def test_status_surfaces_wakeup_failure_to_operator(self, tmp_path):
        """``format_hold_status`` must call out the manual-action warning
        when the wake-up is unregistered. Otherwise the operator never
        learns that the OS scheduler refused."""
        # Pre-populate a hold with wakeup_registered=False (as if a
        # prior enter_quota_hold had a registration failure).
        now = datetime.now(timezone.utc)
        hold = QuotaHold(
            tier="worker",
            provider="anthropic",
            exhausted_at=now,
            resume_at=now + timedelta(hours=1),
            strategy="rolling",
            project_dir=tmp_path,
            job_id="harness-deadbeef",
            wakeup_registered=False,
        )
        write_hold(tmp_path, hold)

        status = format_hold_status(hold, now=now)
        # The warning must be unmistakably visible — not buried in a field dump.
        assert "manual" in status.lower() or "--continue" in status.lower(), (
            f"status text must warn the operator about manual --continue, got:\n{status}"
        )
        # It should be more than just a data field mention.
        # Heuristic: there is at least one line starting with a warning marker.
        warning_lines = [
            line for line in status.splitlines()
            if "⚠" in line or "WARN" in line.upper() or "MANUAL" in line.upper()
        ]
        assert warning_lines, f"expected a WARN/MANUAL line, got:\n{status}"

    def test_status_does_not_warn_when_wakeup_registered(self, tmp_path):
        """A successful registration must NOT spuriously warn."""
        now = datetime.now(timezone.utc)
        hold = QuotaHold(
            tier="worker",
            provider="anthropic",
            exhausted_at=now,
            resume_at=now + timedelta(hours=1),
            strategy="rolling",
            project_dir=tmp_path,
            job_id="harness-deadbeef",
            wakeup_registered=True,
        )
        status = format_hold_status(hold, now=now)
        # No manual-action warning when the wake-up is actually registered.
        assert "manual" not in status.lower(), (
            f"status must not include manual warning when wakeup_registered=True, got:\n{status}"
        )

    def test_old_hold_without_field_reads_back_as_registered(self, tmp_path):
        """Backwards compat: a hold written by the T16e version (no
        ``wakeup_registered`` field) must read back with
        ``wakeup_registered=True`` — otherwise pre-T31 hold files
        would suddenly look broken."""
        now = datetime.now(timezone.utc)
        payload = {
            "tier": "worker",
            "provider": "anthropic",
            "exhausted_at": now.isoformat(),
            "resume_at": (now + timedelta(hours=1)).isoformat(),
            "strategy": "rolling",
            "project_dir": str(tmp_path),
            "job_id": "harness-old",
            "resume_count": 0,
            # No "wakeup_registered" key — this is the T16e format.
        }
        raw_path = tmp_path / HOLD_RELATIVE_PATH
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(payload))

        restored = read_hold(tmp_path)
        assert restored is not None
        assert restored.wakeup_registered is True, (
            "old holds without the field should default to True (preserves prior behaviour)"
        )
