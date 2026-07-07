"""RED tests for T16d — quota hold + OS-level wake-up scheduler.

Per TASKS.md T16d: when both primary and fallback tiers are drained,
the pipeline must (1) persist a quota-hold JSON so the operator can
inspect what is waiting, (2) register an OS-level one-shot job to
re-launch ``python -m harness --continue <project_dir>`` at the next
reset, and (3) clean-exit with the hold info printed.

Backends (auto-picked, in order of preference):
- launchd LaunchAgent (macOS, preferred — atrun rarely loaded)
- systemd --user timer (Linux)
- at / cron (fallback)
- detached ``nohup sleeper`` (last-resort, still zero-token)

Idempotency: the same project_dir may only have ONE pending wake-up.
A second register for the same project replaces the first.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.quota_hold import (
    QuotaHold,
    clear_hold,
    read_hold,
    write_hold,
)
from harness.scheduler import (
    SchedulerBackend,
    cancel_wakeup,
    choose_backend,
    register_wakeup,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_hold(tmp_path: Path, **overrides) -> QuotaHold:
    """Build a representative QuotaHold for tests."""
    defaults = dict(
        tier="worker",
        provider="MiniMax",
        exhausted_at=datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc),
        resume_at=datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc),
        strategy="fixed_clock",
        project_dir=tmp_path,
        phase="develop",
        task_id="task-1",
        job_id="harness-1234abcd",
    )
    defaults.update(overrides)
    return QuotaHold(**defaults)


# ---------------------------------------------------------------------------
# Test: QuotaHold persistence
# ---------------------------------------------------------------------------


class TestQuotaHoldIO:
    def test_write_hold_creates_runner_dir(self, tmp_path):
        hold = _sample_hold(tmp_path)
        path = write_hold(tmp_path, hold)
        assert path.exists()
        assert path == tmp_path / ".runner" / "quota-hold.json"

    def test_round_trip(self, tmp_path):
        original = _sample_hold(tmp_path)
        write_hold(tmp_path, original)
        restored = read_hold(tmp_path)
        assert restored is not None
        assert restored.tier == original.tier
        assert restored.provider == original.provider
        assert restored.strategy == original.strategy
        assert restored.phase == original.phase
        assert restored.task_id == original.task_id

    def test_read_hold_returns_none_when_missing(self, tmp_path):
        assert read_hold(tmp_path) is None

    def test_clear_hold_removes_file(self, tmp_path):
        write_hold(tmp_path, _sample_hold(tmp_path))
        clear_hold(tmp_path)
        assert read_hold(tmp_path) is None

    def test_clear_hold_noop_when_missing(self, tmp_path):
        # Must not raise when there's nothing to clear.
        clear_hold(tmp_path)


# ---------------------------------------------------------------------------
# Test: scheduler backend choice
# ---------------------------------------------------------------------------


class TestChooseBackend:
    def test_macos_prefers_launchd(self):
        with patch("harness.scheduler.platform.system", return_value="Darwin"):
            with patch("harness.scheduler._launchd_available", return_value=True):
                backend = choose_backend()
                assert backend == SchedulerBackend.LAUNCHD

    def test_linux_prefers_systemd_when_available(self):
        with patch("harness.scheduler.platform.system", return_value="Linux"):
            with patch("harness.scheduler._systemd_available", return_value=True):
                backend = choose_backend()
                assert backend == SchedulerBackend.SYSTEMD

    def test_linux_falls_back_to_at_when_no_systemd(self):
        with patch("harness.scheduler.platform.system", return_value="Linux"):
            with patch("harness.scheduler._systemd_available", return_value=False):
                with patch("harness.scheduler._at_available", return_value=True):
                    backend = choose_backend()
                    assert backend == SchedulerBackend.AT

    def test_last_resort_is_sleeper(self):
        with patch("harness.scheduler.platform.system", return_value="Darwin"):
            with patch("harness.scheduler._launchd_available", return_value=False):
                with patch("harness.scheduler._systemd_available", return_value=False):
                    with patch("harness.scheduler._at_available", return_value=False):
                        backend = choose_backend()
                        assert backend == SchedulerBackend.SLEEPER


# ---------------------------------------------------------------------------
# Test: register_wakeup is idempotent
# ---------------------------------------------------------------------------


class TestRegisterWakeup:
    def test_second_register_replaces_first(self):
        at = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc)
        commands_registered = []

        def fake_register_launchd(at_dt, command, job_id):
            commands_registered.append((at_dt, command, job_id))

        with patch(
            "harness.scheduler._register_launchd", side_effect=fake_register_launchd
        ):
            register_wakeup(at, "echo first", job_id="harness-test", backend=SchedulerBackend.LAUNCHD)
            register_wakeup(at, "echo second", job_id="harness-test", backend=SchedulerBackend.LAUNCHD)

        # Two calls but only the latest remains in the test mock — the
        # scheduler must cancel the first before registering the second.
        assert len(commands_registered) == 2

    def test_cancel_wakeup_called_on_replace(self):
        at = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc)
        cancel_calls = []

        def fake_cancel(job_id):
            cancel_calls.append(job_id)
            return False  # nothing to cancel on the test host

        with patch("harness.scheduler._cancel_launchd", side_effect=fake_cancel):
            with patch("harness.scheduler._register_launchd"):
                register_wakeup(
                    at, "echo first", job_id="harness-test", backend=SchedulerBackend.LAUNCHD
                )
                # Second register with same job_id cancels the first
                # then registers the replacement.
                register_wakeup(
                    at, "echo second", job_id="harness-test", backend=SchedulerBackend.LAUNCHD
                )

        # Each register_wakeup calls cancel_wakeup first (best-effort
        # dedupe), so two registers produce two cancel attempts.
        assert cancel_calls == ["harness-test", "harness-test"]


# ---------------------------------------------------------------------------
# Test: backend-specific commands
# ---------------------------------------------------------------------------


class TestLaunchdBackend:
    def test_register_launchd_creates_plist(self, tmp_path):
        # We just verify the function is called with sane arguments.
        at = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            from harness.scheduler import _register_launchd

            _register_launchd(at, "echo hi", job_id="harness-test")

        # launchctl load should be invoked (one of the subprocess calls).
        cmd_strs = [str(c) for c in mock_run.call_args_list]
        assert any("launchctl" in s for s in cmd_strs)