"""T35 — dead-code sweep + sleeper fail-fast on non-POSIX.

Background
----------
Three sources of dead code that have been sitting in the repo for
months (and one latent bug that masquerades as a feature):

1. ``harness/scheduler.py`` defines ``_DISPATCH`` and ``_CANCEL_DISPATCH``
   *twice* (the second copy silently overwrites the first). The actual
   dispatch is an ``if/elif`` chain in ``register_wakeup`` /
   ``cancel_wakeup`` — neither dict is ever consulted.

2. ``harness/pipeline.py::_call_ui_direction`` is defined twice: a
   42-line real implementation at the original location AND a 22-line
   thin delegate added by T24 that forwards to ``UIPhase``. The real
   implementation is dead — UIPhase always calls the delegate.

3. ``harness/ui_phase.py::_ask_version_choice`` is defined twice: a
   33-line first attempt and a 38-line canonical version. The
   canonical wins by Python's last-definition rule; the first is
   dead.

4. ``harness/scheduler.py::_register_sleeper`` has a latent bug: when
   ``os.fork`` is unavailable (Windows), the code falls into the
   ``pid == 0`` branch and runs ``time.sleep + os.system`` in the
   parent process — *blocking the harness*. Plus the command is
   passed to ``os.system`` (shell-parsed) instead of a subprocess
   list (no shell, no quoting risk).

T35 removes the dead code and adds a fail-fast on non-POSIX.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import harness.scheduler as scheduler
import harness.ui_phase as ui_phase


# ---------------------------------------------------------------------------
# 1. scheduler._DISPATCH / _CANCEL_DISPATCH must be defined exactly once
# ---------------------------------------------------------------------------


class TestDispatchDeduplicated:
    """The dispatch tables are dead — the real routing is an if/elif
    chain. Both tables must be removed entirely."""

    def test_dispatch_dict_removed(self):
        """``_DISPATCH`` is no longer a module-level name on scheduler."""
        assert not hasattr(scheduler, "_DISPATCH"), (
            "scheduler._DISPATCH must be removed; the real dispatch is an "
            "if/elif chain. Run: grep -n '_DISPATCH' harness/scheduler.py"
        )

    def test_cancel_dispatch_dict_removed(self):
        assert not hasattr(scheduler, "_CANCEL_DISPATCH"), (
            "scheduler._CANCEL_DISPATCH must be removed; the real cancel "
            "routing is an if/elif chain."
        )

    def test_no_duplicate_definitions_remain(self):
        """Sanity: grep the source for either name to catch leftovers
        that the ``hasattr`` check above would miss (e.g. dead branches
        inside conditionals)."""
        src = Path(scheduler.__file__).read_text()
        # Each name must appear zero times in the file (defs + uses both).
        assert "_DISPATCH" not in src, (
            "scheduler source still contains '_DISPATCH'; dead code remains"
        )
        assert "_CANCEL_DISPATCH" not in src, (
            "scheduler source still contains '_CANCEL_DISPATCH'; dead code remains"
        )


# ---------------------------------------------------------------------------
# 2. Pipeline._call_ui_direction: the 42-line real impl is gone
# ---------------------------------------------------------------------------


class TestPipelineCallUIDirectionDeduped:
    def test_pipeline_has_one_call_ui_direction(self):
        """The 42-line dead implementation was the original; T24 added
        a thin delegate on top. The dead one is now removed, leaving
        only the delegate. Source-grep proves there's exactly one
        ``def _call_ui_direction`` in pipeline.py."""
        from harness import pipeline

        src = Path(pipeline.__file__).read_text()
        count = src.count("def _call_ui_direction")
        assert count == 1, (
            f"pipeline.py must have exactly one _call_ui_direction "
            f"(the T24 delegate); found {count} defs"
        )

    def test_pipeline_call_ui_direction_is_thin_delegate(self):
        """The remaining one must be the thin delegate — body must
        call ``UIPhase(self)._call_ui_direction(...)`` rather than
        contain the full prompt-assembly logic."""
        from harness import pipeline

        src = Path(pipeline.__file__).read_text()
        # Find the single def line; check the next 30 lines for the
        # UIPhase delegation pattern.
        idx = src.find("def _call_ui_direction")
        assert idx > 0
        body_window = src[idx: idx + 2000]
        assert "UIPhase(self)" in body_window, (
            "Pipeline._call_ui_direction must delegate to UIPhase; "
            "the real implementation belongs on UIPhase only"
        )


# ---------------------------------------------------------------------------
# 3. UIPhase._ask_version_choice: only the canonical remains
# ---------------------------------------------------------------------------


class TestUIPhaseAskVersionChoiceDeduped:
    def test_ui_phase_has_one_ask_version_choice(self):
        """The 33-line first attempt at _ask_version_choice is removed;
        the canonical 38-line version (added later in the same file)
        is the sole definition."""
        src = Path(ui_phase.__file__).read_text()
        count = src.count("def _ask_version_choice")
        assert count == 1, (
            f"ui_phase.py must have exactly one _ask_version_choice; "
            f"found {count} defs"
        )


# ---------------------------------------------------------------------------
# 4. _register_sleeper fails fast on non-POSIX
# ---------------------------------------------------------------------------


class TestRegisterSleeperFailFast:
    """The sleeper backend shells out via ``os.system`` after a fork.
    On a host without ``os.fork`` (Windows), the old code fell into
    the ``pid == 0`` branch and blocked the parent with time.sleep +
    os.system. T35 makes this fail loudly so the operator picks a
    different backend."""

    def test_sleeper_without_fork_raises_not_implemented(self):
        """When ``os.fork`` is missing (e.g. Windows), ``_register_sleeper``
        must raise ``NotImplementedError`` with a message that points
        the operator at the working backends."""
        # Build a context where hasattr(os, "fork") is False.
        # We can't pop os.fork on Linux (it's a built-in), so we
        # patch the scheduler module's view of os.
        from datetime import datetime, timezone

        import harness.scheduler as sched

        # Patch sched.os to be a stub that lacks "fork" — hasattr
        # returns False, triggering the new fail-fast branch.
        class _OsNoFork:
            pass

        original_os = sched.os
        sched.os = _OsNoFork()
        try:
            try:
                sched._register_sleeper(
                    at=datetime.now(timezone.utc),
                    command="echo hi",
                    job_id="harness-test",
                )
            except NotImplementedError as exc:
                # The message must name a workable backend so the
                # operator knows what to do instead.
                msg = str(exc).lower()
                assert "launchd" in msg or "systemd" in msg or "at" in msg, (
                    f"NotImplementedError should suggest a working backend; "
                    f"got: {exc}"
                )
                return
            except Exception as exc:  # pragma: no cover - wrong failure mode
                pytest.fail(
                    f"_register_sleeper must raise NotImplementedError on "
                    f"non-fork systems; got {type(exc).__name__}: {exc}"
                )
            pytest.fail(
                "_register_sleeper must raise NotImplementedError on "
                "non-fork systems; no exception was raised"
            )
        finally:
            sched.os = original_os

    def test_sleeper_with_fork_does_not_block(self, monkeypatch):
        """When fork is available, _register_sleeper must NOT call
        ``time.sleep`` or ``os.system`` in the *parent* process —
        those belong to the detached child. The parent should just
        return after the fork."""
        from datetime import datetime, timedelta, timezone
        import time as time_mod

        # Track whether sleep / system are called in the parent.
        sleep_called = []
        system_called = []

        import harness.scheduler as sched

        def fake_fork():
            sleep_called.append("fork")
            return 12345  # parent branch (pid > 0)

        def fake_sleep(*args, **kwargs):
            sleep_called.append(("sleep", args))

        def fake_system(*args, **kwargs):
            system_called.append(args)

        # ``time`` is imported inside _register_sleeper (local scope),
        # so we patch the *module*'s time.sleep — that's what the
        # inner ``import time`` resolves to. We also patch
        # sched.os.fork / sched.os.system on the scheduler module's
        # own ``os`` reference (imported at top-level).
        monkeypatch.setattr(sched.os, "fork", fake_fork)
        monkeypatch.setattr(sched.os, "system", fake_system)
        monkeypatch.setattr(time_mod, "sleep", fake_sleep)

        sched._register_sleeper(
            at=datetime.now(timezone.utc) + timedelta(seconds=5),
            command="echo hi",
            job_id="harness-test",
        )

        # Parent must NOT have slept or called system.
        sleep_in_parent = [s for s in sleep_called if isinstance(s, tuple)]
        assert not sleep_in_parent, (
            f"parent process must not call time.sleep; got {sleep_in_parent}"
        )
        assert not system_called, (
            f"parent process must not call os.system; got {system_called}"
        )
