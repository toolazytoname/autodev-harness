"""RED tests for T23 — eliminate ``os.environ`` in-place mutation.

Per TASKS.md T23: ``pipeline.py`` used ``os.environ[env_var] = ""`` to
mark feedback as "consumed" — a process-global mutation that pollutes
the next test, races between Pipeline instances, and violates the
CLAUDE.md immutability rule. Fix: track consumption on the Pipeline
instance (``self._consumed_feedback: set[str]``) and leave ``os.environ``
read-only.

These tests pin the new behaviour:

1. ``os.environ`` is never written by ``_ask_feedback`` /
   ``_ask_version_choice`` (proven by a hostile probe that fails on
   any ``os.environ.__setitem__``).
2. The same Pipeline instance consumes each env var exactly once
   (second read returns "" so feedback loops terminate).
3. Two Pipeline instances do not interfere — each sees its own copy.
4. TTY mode never touches the consumed set (it's a no-TTY code path).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.base import AgentResult
from harness.pipeline import Pipeline, PipelineConfig
from harness.router import ModelRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_result(text: str = "# plan") -> AgentResult:
    return AgentResult(stdout=text, stderr="", exit_code=0)


def make_pipeline(project_dir: Path, adapter=None, router=None) -> Pipeline:
    return Pipeline(
        config=PipelineConfig(project_dir=project_dir, mode="new", max_iterations=3),
        adapter=adapter or MagicMock(),
        router=router or MagicMock(spec=ModelRouter),
    )


class _HostileEnviron:
    """Probe that fails the test the moment anyone writes to ``os.environ``.

    Used to prove the feedback helpers don't mutate the process env.
    Wrapping ``os.environ`` (a ``Mapping``) by replacing ``__setitem__``
    is enough; ``os.environ.pop`` / ``os.environ.clear`` go through
    ``__delitem__`` which we also catch. Reads (``os.environ.get``) are
    allowed because they don't mutate state.
    """

    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def __enter__(self):
        self._orig_setitem = os.environ.__setitem__
        self._orig_delitem = os.environ.__delitem__

        def setitem(k, v):
            self.writes.append((k, v))
            raise AssertionError(
                f"os.environ was written: {k!r}={v!r} — T23 forbids this"
            )

        def delitem(k):
            self.writes.append((k, "<deleted>"))
            raise AssertionError(
                f"os.environ was deleted: {k!r} — T23 forbids this"
            )

        os.environ.__setitem__ = setitem
        os.environ.__delitem__ = delitem
        return self

    def __exit__(self, *exc):
        os.environ.__setitem__ = self._orig_setitem
        os.environ.__delitem__ = self._orig_delitem


# ---------------------------------------------------------------------------
# Test: instance-level consumed set
# ---------------------------------------------------------------------------


class TestConsumedFeedbackSet:
    def test_init_defaults_to_empty_set(self, tmp_path):
        p = make_pipeline(tmp_path)
        assert hasattr(p, "_consumed_feedback")
        assert p._consumed_feedback == set()

    def test_two_instances_have_independent_sets(self, tmp_path):
        p1 = make_pipeline(tmp_path)
        p2 = make_pipeline(tmp_path)
        p1._consumed_feedback.add("AUTODEV_PLAN_FEEDBACK")
        assert "AUTODEV_PLAN_FEEDBACK" in p1._consumed_feedback
        assert "AUTODEV_PLAN_FEEDBACK" not in p2._consumed_feedback


# ---------------------------------------------------------------------------
# Test: _ask_feedback leaves os.environ untouched
# ---------------------------------------------------------------------------


class TestAskFeedbackNoMutation:
    def test_first_call_returns_env_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTODEV_PLAN_FEEDBACK", "请简化")
        p = make_pipeline(tmp_path)
        with patch("harness.pipeline._is_interactive", return_value=False), \
             _HostileEnviron():
            value = p._ask_feedback("> ", "AUTODEV_PLAN_FEEDBACK")
        assert value == "请简化"
        assert "AUTODEV_PLAN_FEEDBACK" in p._consumed_feedback

    def test_second_call_returns_empty_after_consume(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTODEV_PLAN_FEEDBACK", "请简化")
        p = make_pipeline(tmp_path)
        with patch("harness.pipeline._is_interactive", return_value=False), \
             _HostileEnviron():
            first = p._ask_feedback("> ", "AUTODEV_PLAN_FEEDBACK")
            second = p._ask_feedback("> ", "AUTODEV_PLAN_FEEDBACK")
        assert first == "请简化"
        # Critical: env value stays in os.environ but the *instance* treats
        # it as consumed — so feedback loops terminate without global mutation.
        assert second == ""
        assert os.environ.get("AUTODEV_PLAN_FEEDBACK") == "请简化"

    def test_empty_env_returns_empty_without_consuming(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUTODEV_PLAN_FEEDBACK", raising=False)
        p = make_pipeline(tmp_path)
        with patch("harness.pipeline._is_interactive", return_value=False), \
             _HostileEnviron():
            value = p._ask_feedback("> ", "AUTODEV_PLAN_FEEDBACK")
        assert value == ""
        # Never consumed — would-be 2nd call would also see ""
        assert "AUTODEV_PLAN_FEEDBACK" not in p._consumed_feedback

    def test_two_instances_each_get_their_own_copy(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTODEV_PLAN_FEEDBACK", "请简化")
        p1 = make_pipeline(tmp_path)
        p2 = make_pipeline(tmp_path)
        with patch("harness.pipeline._is_interactive", return_value=False), \
             _HostileEnviron():
            assert p1._ask_feedback("> ", "AUTODEV_PLAN_FEEDBACK") == "请简化"
            assert p2._ask_feedback("> ", "AUTODEV_PLAN_FEEDBACK") == "请简化"
        # Both instances saw the value; neither polluted the env.

    def test_tty_path_does_not_consume(self, tmp_path, monkeypatch):
        # In TTY mode the env var is irrelevant; input() is the source.
        monkeypatch.setenv("AUTODEV_PLAN_FEEDBACK", "ignored")
        p = make_pipeline(tmp_path)
        with patch("harness.pipeline._is_interactive", return_value=True), \
             patch("builtins.input", return_value="human input"):
            value = p._ask_feedback("> ", "AUTODEV_PLAN_FEEDBACK")
        assert value == "human input"
        # No consumption: TTY mode must not accidentally mark env as used.
        assert "AUTODEV_PLAN_FEEDBACK" not in p._consumed_feedback


# ---------------------------------------------------------------------------
# Test: _ask_version_choice leaves os.environ untouched
# ---------------------------------------------------------------------------


class TestAskVersionChoiceNoMutation:
    def test_choice_consumed_on_first_call(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTODEV_UI_CHOICE", "2")
        monkeypatch.delenv("AUTODEV_UI_FEEDBACK", raising=False)
        p = make_pipeline(tmp_path)
        with patch("harness.pipeline._is_interactive", return_value=False), \
             _HostileEnviron():
            choice, feedback = p._ask_version_choice(4)
        assert choice == "2"
        assert feedback == ""
        assert "AUTODEV_UI_CHOICE" in p._consumed_feedback

    def test_feedback_consumed_on_first_call(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUTODEV_UI_CHOICE", raising=False)
        monkeypatch.setenv("AUTODEV_UI_FEEDBACK", "more whitespace")
        p = make_pipeline(tmp_path)
        with patch("harness.pipeline._is_interactive", return_value=False), \
             _HostileEnviron():
            choice, feedback = p._ask_version_choice(4)
        assert choice == ""
        assert feedback == "more whitespace"
        assert "AUTODEV_UI_FEEDBACK" in p._consumed_feedback

    def test_second_call_falls_back_to_accept_first(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTODEV_UI_CHOICE", "3")
        monkeypatch.delenv("AUTODEV_UI_FEEDBACK", raising=False)
        p = make_pipeline(tmp_path)
        with patch("harness.pipeline._is_interactive", return_value=False), \
             _HostileEnviron():
            first = p._ask_version_choice(4)
            second = p._ask_version_choice(4)
        assert first == ("3", "")
        # Second call must NOT repeat — that's why we mark consumed.
        assert second == ("accept_first", "")
        # Env var still present in os.environ — we just ignore it now.
        assert os.environ.get("AUTODEV_UI_CHOICE") == "3"

    def test_no_env_defaults_to_accept_first(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUTODEV_UI_CHOICE", raising=False)
        monkeypatch.delenv("AUTODEV_UI_FEEDBACK", raising=False)
        p = make_pipeline(tmp_path)
        with patch("harness.pipeline._is_interactive", return_value=False), \
             _HostileEnviron():
            choice, feedback = p._ask_version_choice(4)
        assert choice == "accept_first"
        assert feedback == ""
        assert p._consumed_feedback == set()


# ---------------------------------------------------------------------------
# Test: existing feedback-loop regression
# ---------------------------------------------------------------------------


class TestPlanFeedbackLoopTerminates:
    def test_plan_feedback_loop_terminates_with_env(self, tmp_path, monkeypatch):
        """Regression: the plan phase used to set os.environ[...]="" after
        reading feedback; that mutation also affected pytest monkeypatch.
        The loop must still terminate (2 calls: initial + 1 regen) under
        T23's instance-level consumption."""
        (tmp_path / "000-brief.md").write_text("# 项目需求")
        (tmp_path / "001-research-report.md").write_text("# 研究报告")

        adapter = MagicMock()
        adapter.run.return_value = _agent_result("# 计划")
        p = make_pipeline(tmp_path, adapter=adapter)

        monkeypatch.setenv("AUTODEV_PLAN_FEEDBACK", "简化数据库设计")
        with patch("harness.pipeline._is_interactive", return_value=False), \
             _HostileEnviron():
            p.phase_plan()

        # Initial call + exactly one regen; loop must terminate.
        assert adapter.run.call_count == 2
        # HostileEnviron would have raised on any write; reaching here means
        # the env var was never mutated. Belt-and-braces explicit check:
        assert os.environ.get("AUTODEV_PLAN_FEEDBACK") == "简化数据库设计"