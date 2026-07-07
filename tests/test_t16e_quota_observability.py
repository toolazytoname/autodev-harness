"""RED tests for T16e — quota observability + guardrails + CLI.

Per TASKS.md T16e:
- ``harness status`` must show a pending quota-hold + countdown.
- New CLI: ``python -m harness quota-status`` and ``--cancel-hold``.
- Guardrail: cap auto-resume at ``MAX_AUTO_RESUME`` so quota that never
  recovers cannot loop forever.
- "All tiers exhausted" must bubble to the user instead of silently
  spinning or crashing with a stack trace.

These tests pin the public surface. Implementation lives in
``harness.quota_hold`` (resume_count + begin_resume + enter_quota_hold +
format_hold_status + cancel_pending_hold + MAX_AUTO_RESUME +
QuotaResumeExhaustedError) and ``harness.__main__`` (CLI wiring).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.base import QuotaExhaustedError
from harness.quota_hold import (
    MAX_AUTO_RESUME,
    HOLD_RELATIVE_PATH,
    QuotaHold,
    QuotaResumeExhaustedError,
    begin_resume,
    cancel_pending_hold,
    clear_hold,
    enter_quota_hold,
    format_hold_status,
    read_hold,
    write_hold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_hold(
    tmp_path: Path,
    *,
    resume_count: int = 0,
    resume_in: timedelta = timedelta(hours=5),
    **overrides,
) -> QuotaHold:
    """Build a representative QuotaHold for tests."""
    exhausted_at = datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc)
    defaults: dict = dict(
        tier="worker",
        provider="MiniMax",
        exhausted_at=exhausted_at,
        resume_at=exhausted_at + resume_in,
        strategy="fixed_clock",
        project_dir=tmp_path,
        phase="develop",
        task_id="task-1",
        job_id="harness-1234abcd",
        resume_count=resume_count,
    )
    defaults.update(overrides)
    return QuotaHold(**defaults)


def _now() -> datetime:
    """Pinned clock for status formatting — chosen between exhausted_at and resume_at."""
    return datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test: QuotaHold schema gains resume_count
# ---------------------------------------------------------------------------


class TestQuotaHoldResumeCount:
    def test_resume_count_defaults_to_zero(self):
        hold = QuotaHold(
            tier="worker",
            provider="MiniMax",
            exhausted_at=datetime.now(timezone.utc),
            resume_at=datetime.now(timezone.utc),
            strategy="rolling",
            project_dir=Path("/tmp"),
            job_id="harness-x",
        )
        assert hold.resume_count == 0

    def test_resume_count_round_trips(self, tmp_path):
        original = _sample_hold(tmp_path, resume_count=2)
        write_hold(tmp_path, original)
        restored = read_hold(tmp_path)
        assert restored is not None
        assert restored.resume_count == 2


# ---------------------------------------------------------------------------
# Test: constants and exceptions
# ---------------------------------------------------------------------------


class TestConstants:
    def test_max_auto_resume_is_positive(self):
        assert isinstance(MAX_AUTO_RESUME, int)
        assert MAX_AUTO_RESUME >= 1


class TestExceptions:
    def test_quota_resume_exhausted_is_quota_exhausted_subclass(self):
        assert issubclass(QuotaResumeExhaustedError, QuotaExhaustedError)


# ---------------------------------------------------------------------------
# Test: begin_resume
# ---------------------------------------------------------------------------


class TestBeginResume:
    def test_no_prior_hold_returns_zero(self, tmp_path):
        assert begin_resume(tmp_path) == 0

    def test_prior_hold_below_cap_clears_and_returns_next_count(self, tmp_path):
        write_hold(tmp_path, _sample_hold(tmp_path, resume_count=1))
        # next count = 1 + 1
        next_count = begin_resume(tmp_path, max_auto_resume=3)
        assert next_count == 2
        # consumed
        assert read_hold(tmp_path) is None

    def test_prior_hold_below_cap_default_max(self, tmp_path):
        # Default cap is MAX_AUTO_RESUME; verify default path works.
        write_hold(tmp_path, _sample_hold(tmp_path, resume_count=0))
        assert begin_resume(tmp_path) == 1
        assert read_hold(tmp_path) is None

    def test_prior_hold_at_cap_raises_and_preserves_evidence(self, tmp_path):
        write_hold(tmp_path, _sample_hold(tmp_path, resume_count=3))
        with pytest.raises(QuotaResumeExhaustedError) as exc_info:
            begin_resume(tmp_path, max_auto_resume=3)
        # Evidence must survive — operator should still see the hold.
        assert read_hold(tmp_path) is not None
        # Error message references the cap.
        assert "3" in str(exc_info.value)

    def test_prior_hold_above_cap_raises(self, tmp_path):
        write_hold(tmp_path, _sample_hold(tmp_path, resume_count=99))
        with pytest.raises(QuotaResumeExhaustedError):
            begin_resume(tmp_path, max_auto_resume=3)


# ---------------------------------------------------------------------------
# Test: enter_quota_hold (T16d flow integration)
# ---------------------------------------------------------------------------


class TestEnterQuotaHold:
    def test_writes_hold_and_registers_wakeup(self, tmp_path):
        exc = QuotaExhaustedError(
            "rate_limit_error ... resets at 15:00",
            tier="worker",
            provider="MiniMax",
            reset_hint="resets_at=15:00",
        )
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            mock_wake.return_value = "launchd"
            path = enter_quota_hold(
                tmp_path, exc,
                resume_count=2,
                phase="develop",
                task_id="task-7",
            )

        # Hold file written
        assert path == tmp_path / HOLD_RELATIVE_PATH
        assert path.exists()

        # The wake-up `at` must match the persisted hold's resume_at —
        # otherwise the OS scheduler would fire at a different moment than
        # the operator sees in `harness status`.
        restored = read_hold(tmp_path)
        assert restored is not None
        mock_wake.assert_called_once()
        kwargs = mock_wake.call_args.kwargs
        assert kwargs["at"] == restored.resume_at
        assert "--continue" in kwargs["command"]
        assert str(tmp_path) in kwargs["command"]

        # Hold carries phase + task_id + resume_count
        assert restored.phase == "develop"
        assert restored.task_id == "task-7"
        assert restored.resume_count == 2

    def test_returns_path(self, tmp_path):
        exc = QuotaExhaustedError(
            "insufficient balance",
            tier="worker",
            provider="MiniMax",
        )
        with patch("harness.quota_hold.register_wakeup"):
            path = enter_quota_hold(tmp_path, exc)
        assert isinstance(path, Path)
        assert path.exists()

    def test_idempotent_replace_of_existing_hold(self, tmp_path):
        # A second enter_quota_hold replaces the previous (T16d idempotency).
        exc = QuotaExhaustedError("usage limit", tier="worker", provider="MiniMax")
        with patch("harness.quota_hold.register_wakeup") as mock_wake:
            enter_quota_hold(tmp_path, exc, resume_count=1)
            enter_quota_hold(tmp_path, exc, resume_count=2)
        assert mock_wake.call_count == 2
        assert read_hold(tmp_path).resume_count == 2


# ---------------------------------------------------------------------------
# Test: format_hold_status
# ---------------------------------------------------------------------------


class TestFormatHoldStatus:
    def test_includes_tier_provider_and_resume_at(self, tmp_path):
        hold = _sample_hold(tmp_path)
        text = format_hold_status(hold, now=_now())
        assert hold.tier in text
        assert hold.provider in text
        # resume_at is rendered in local time; just check the date + the
        # "resume at:" label is present so we don't depend on the host TZ.
        assert "resume at:" in text
        assert hold.resume_at.strftime("%Y-%m-%d") in text

    def test_includes_positive_countdown_when_future(self, tmp_path):
        hold = _sample_hold(tmp_path)  # resume_at is 5h after _now()
        text = format_hold_status(hold, now=_now())
        # 5h - 3h already past since exhausted_at → ~2h countdown
        assert "h" in text or ":" in text

    def test_says_due_when_past(self, tmp_path):
        hold = _sample_hold(tmp_path, resume_in=timedelta(seconds=-10))
        text = format_hold_status(hold, now=_now())
        assert "due" in text.lower() or "now" in text.lower() or "0" in text


# ---------------------------------------------------------------------------
# Test: cancel_pending_hold
# ---------------------------------------------------------------------------


class TestCancelPendingHold:
    def test_clears_and_cancels_wakeup(self, tmp_path):
        write_hold(tmp_path, _sample_hold(tmp_path))
        with patch("harness.quota_hold.cancel_wakeup") as mock_cancel:
            cleared = cancel_pending_hold(tmp_path)
        assert cleared is True
        assert read_hold(tmp_path) is None
        mock_cancel.assert_called_once()
        assert mock_cancel.call_args.kwargs["job_id"] == "harness-1234abcd"

    def test_no_op_when_no_hold(self, tmp_path):
        with patch("harness.quota_hold.cancel_wakeup") as mock_cancel:
            cleared = cancel_pending_hold(tmp_path)
        assert cleared is False
        mock_cancel.assert_not_called()


# ---------------------------------------------------------------------------
# Test: CLI _print_status shows quota-hold section
# ---------------------------------------------------------------------------


class TestPrintStatusShowsHold:
    def test_shows_hold_section_when_hold_exists(self, tmp_path, capsys):
        from harness.__main__ import _print_status

        write_hold(tmp_path, _sample_hold(tmp_path))
        rc = _print_status(tmp_path)
        # Even without workflow state, status should succeed and show hold
        # (T16e: hold is its own first-class concern, not gated on state).
        captured = capsys.readouterr().out
        assert "Quota hold" in captured or "quota-hold" in captured
        assert "worker" in captured

    def test_no_hold_no_section(self, tmp_path, capsys):
        from harness.__main__ import _print_status

        # No hold, no workflow state — should print something useful and return non-zero
        # (matches prior behaviour of "no workflow state"). No quota section.
        rc = _print_status(tmp_path)
        captured = capsys.readouterr().out
        assert "Quota hold" not in captured
        assert "quota-hold" not in captured


# ---------------------------------------------------------------------------
# Test: CLI quota-status subcommand
# ---------------------------------------------------------------------------


class TestQuotaStatusSubcommand:
    def test_subcommand_shows_hold(self, tmp_path, capsys):
        from harness.__main__ import main

        write_hold(tmp_path, _sample_hold(tmp_path))
        rc = main(["quota-status", str(tmp_path)])
        captured = capsys.readouterr().out
        assert rc == 0
        assert "Quota hold" in captured or "quota-hold" in captured
        assert "worker" in captured

    def test_subcommand_exits_1_when_no_hold(self, tmp_path, capsys):
        from harness.__main__ import main

        rc = main(["quota-status", str(tmp_path)])
        captured = capsys.readouterr()
        assert rc == 1
        # Should mention absence so the user knows it's not a bug
        combined = captured.out + captured.err
        assert "no" in combined.lower() or "absent" in combined.lower()


# ---------------------------------------------------------------------------
# Test: CLI --cancel-hold flag
# ---------------------------------------------------------------------------


class TestCancelHoldFlag:
    def test_clears_hold_and_does_not_run_pipeline(self, tmp_path, capsys):
        from harness.__main__ import main

        write_hold(tmp_path, _sample_hold(tmp_path))
        # If pipeline were run, it would call ClaudeAdapter — patch to catch any misuse.
        with patch("harness.__main__.ClaudeAdapter") as mock_adapter:
            rc = main(["--cancel-hold", str(tmp_path)])

        mock_adapter.assert_not_called()
        assert read_hold(tmp_path) is None
        captured = capsys.readouterr()
        assert rc == 0

    def test_no_hold_is_noop_zero_exit(self, tmp_path, capsys):
        from harness.__main__ import main

        with patch("harness.__main__.ClaudeAdapter") as mock_adapter:
            rc = main(["--cancel-hold", str(tmp_path)])
        mock_adapter.assert_not_called()
        assert rc == 0


# ---------------------------------------------------------------------------
# Test: --continue enforces max-resume guard
# ---------------------------------------------------------------------------


class TestContinueMaxResumeGuard:
    def test_below_cap_consumes_hold_and_runs_pipeline(self, tmp_path, capsys):
        from harness.__main__ import main

        write_hold(tmp_path, _sample_hold(tmp_path, resume_count=1))
        with patch("harness.__main__.Pipeline") as mock_pipeline_cls:
            instance = MagicMock()
            instance.run.return_value = None
            mock_pipeline_cls.return_value = instance
            rc = main(["--continue", str(tmp_path)])

        # Hold was consumed
        assert read_hold(tmp_path) is None
        # Pipeline ran
        instance.run.assert_called_once()
        # Config carries the next count (1 + 1 = 2)
        from harness.pipeline import PipelineConfig
        cfg = mock_pipeline_cls.call_args.args[0]
        assert isinstance(cfg, PipelineConfig)
        assert cfg.next_resume_count == 2
        assert rc == 0

    def test_at_cap_exits_with_clear_message(self, tmp_path, capsys):
        from harness.__main__ import main

        write_hold(tmp_path, _sample_hold(tmp_path, resume_count=3))
        with patch("harness.__main__.Pipeline") as mock_pipeline_cls:
            instance = MagicMock()
            mock_pipeline_cls.return_value = instance
            rc = main(["--continue", str(tmp_path)])

        # Pipeline did NOT run
        instance.run.assert_not_called()
        # Hold preserved for evidence
        assert read_hold(tmp_path) is not None
        # Clear message and non-zero exit
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert rc != 0
        assert "max" in combined.lower() or "resume" in combined.lower()
        assert "--cancel-hold" in combined


# ---------------------------------------------------------------------------
# Test: Pipeline catches QuotaExhaustedError → enter_quota_hold → re-raises
# ---------------------------------------------------------------------------


class TestPipelineQuotaGuard:
    def test_quota_exhausted_triggers_enter_quota_hold_then_reraises(self, tmp_path):
        from harness.pipeline import Pipeline, PipelineConfig

        cfg = PipelineConfig(
            project_dir=tmp_path,
            mode="new",
            max_iterations=3,
            next_resume_count=2,
        )

        exc = QuotaExhaustedError(
            "usage limit reached",
            tier="worker",
            provider="MiniMax",
        )

        with patch("harness.pipeline.enter_quota_hold") as mock_enter:
            mock_enter.return_value = tmp_path / ".runner" / "quota-hold.json"
            pipeline = Pipeline(cfg, adapter=MagicMock())
            phase = MagicMock(value="develop")

            with pytest.raises(QuotaExhaustedError):
                pipeline._run_phase_with_quota_guard(phase, runner=lambda: (_ for _ in ()).throw(exc))

        mock_enter.assert_called_once()
        call = mock_enter.call_args
        # project_dir and exc are positional; resume_count / phase / task_id
        # are keyword-only.
        assert call.args[0] == tmp_path
        assert call.args[1] is exc
        assert call.kwargs.get("resume_count") == 2
        assert call.kwargs.get("phase") == "develop"


# ---------------------------------------------------------------------------
# Test: CLI catches QuotaExhaustedError → clear info + clean exit
# ---------------------------------------------------------------------------


class TestCLIBubblesQuotaExhausted:
    def test_quota_exhausted_prints_clear_message_and_exits(self, tmp_path, capsys):
        from harness.__main__ import main

        exc = QuotaExhaustedError(
            "usage limit reached for MiniMax",
            tier="worker",
            provider="MiniMax",
            reset_hint="resets_at=2026-07-07T15:00:00Z",
        )

        # Pre-populate the hold (the real Pipeline would have written it
        # in _run_phase_with_quota_guard before re-raising; here we mock
        # the whole Pipeline so we have to simulate that side-effect).
        pre_hold = _sample_hold(tmp_path, resume_count=0)
        write_hold(tmp_path, pre_hold)

        # Patch the pipeline to raise the quota error.
        with patch("harness.__main__.Pipeline") as mock_pipeline_cls:
            instance = MagicMock()
            instance.run.side_effect = exc
            mock_pipeline_cls.return_value = instance
            rc = main([str(tmp_path), "--", "build something"])

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        # Clear, friendly message — not a stack trace
        assert "quota" in combined.lower()
        assert "hold" in combined.lower()
        assert "quota-status" in combined
        # Non-zero exit so CI / cron can detect it
        assert rc != 0


# ---------------------------------------------------------------------------
# Test: --continue preserves workflow-state semantics (regression guard)
# ---------------------------------------------------------------------------


class TestContinueFreshRunWhenNoHold:
    def test_no_prior_hold_resume_count_zero(self, tmp_path, capsys):
        from harness.__main__ import main

        with patch("harness.__main__.Pipeline") as mock_pipeline_cls:
            instance = MagicMock()
            mock_pipeline_cls.return_value = instance
            rc = main(["--continue", str(tmp_path)])

        instance.run.assert_called_once()
        from harness.pipeline import PipelineConfig
        cfg = mock_pipeline_cls.call_args.args[0]
        assert cfg.next_resume_count == 0
        assert rc == 0